'''
Created on Apr 25, 2012

@package: superdesk media archive
@copyright: 2012 Sourcefabric o.p.s.
@license: http://www.gnu.org/licenses/gpl-3.0.txt
@author: Gabriel Nistor

Implementation for the image persistence API.
'''

from ..api import image_info as api
from ..api.image_persist import IImagePersistanceService
from ..meta.image_data import ImageData
from ..meta.image_info import ImageInfo
from ..meta.meta_data import MetaDataMapped
from ..meta.meta_type import MetaTypeMapped
from superdesk.media_archive.core.spec import IMetaDataHandler
from ally.api.model import Content
from ally.container import wire
from ally.container.ioc import injected
from ally.support.api.util_service import copy
from ally.support.sqlalchemy.session import SessionSupport
from ally.support.sqlalchemy.util_service import handle
from ally.support.util_io import pipe
from cdm.spec import PathNotFound
from datetime import datetime
from genericpath import isdir
from os.path import join, getsize
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import NoResultFound
import os
import subprocess
from ..core.spec import IThumbnailManager
from ally.support.util_io import openURI, timestampURI
from superdesk.media_archive.core.impl.meta_service_base import thumbnailFormatFor
from ally.support.util_sys import pythonPath


# --------------------------------------------------------------------

@injected
class ImagePersistanceService(IImagePersistanceService, IMetaDataHandler, SessionSupport):
    '''
    Provides the service that handles the @see: IImagePersistanceService.
    '''

    image_dir_path = join('workspace', 'media_archive', 'image_queue'); wire.config('image_dir_path', doc='''
    The folder path where the images are queued for processing''')
    format_file_name = '%(id)s.%(file)s'; wire.config('format_file_name', doc='''
    The format for the images file names in the media archive''')
    default_file_name = 'unknown'; wire.config('default_file_name', doc='''
    The default file name if non is specified''')

    imageTypeKey = 'image'
    # The key for the meta type image
    
    thumbnailManager = IThumbnailManager; wire.entity('thumbnailManager')
    # Provides the thumbnail referencer

    def __init__(self):
        assert isinstance(self.image_dir_path, str), 'Invalid image directory %s' % self.image_dir_path
        assert isinstance(self.format_file_name, str), 'Invalid format file name %s' % self.format_file_name
        assert isinstance(self.default_file_name, str), 'Invalid default file name %s' % self.default_file_name
        assert isinstance(self.imageTypeKey, str), 'Invalid meta type image key %s' % self.imageTypeKey
        
        SessionSupport.__init__(self)

        if not os.path.exists(self.image_dir_path): os.makedirs(self.image_dir_path)
        if not isdir(self.image_dir_path) or not os.access(self.image_dir_path, os.W_OK):
            raise IOError('Unable to access the repository directory %s' % self.image_dir_path)

        self._metaTypeId = None

    def insertAll(self, imageInfo, image):
        '''
        @see: IImagePersistanceService.insert
        '''
        assert isinstance(imageInfo, api.ImageInfo), 'Invalid image info %s' % imageInfo
        assert isinstance(image, Content), 'Invalid image content %s' % image

        imageData = ImageData()
        imageData.CreatedOn = datetime.now()
        imageData.typeId = self._typeId()

        try:
            self.session().add(imageData)
            self.session().flush((imageData,))

            reference = self.format_file_name % {'id': imageData.Id, 'file': image.getName() or self.default_file_name}
            path = join(self.image_dir_path, reference)
            with open(path, 'wb') as fobj: pipe(image, fobj)

            assert isinstance(imageData, MetaDataMapped)
            imageData.reference = reference
            imageData.SizeInBytes = getsize(path)
            #TODO: implement read the actual meta data
            imageData.Width = 100
            imageData.Height = 100

            self.session().flush((imageData,))

            imageInfoDb = copy(imageInfo, ImageInfo())
            imageInfoDb.MetaData = imageData.Id

            self.session().add(imageInfoDb)
            self.session().flush((imageInfoDb,))

        except SQLAlchemyError as e: handle(e, imageInfoDb)

        imageInfo.Id = imageInfoDb.Id
        return imageInfoDb.Id

    # ----------------------------------------------------------------
    def extractNumber(self, line):
        for s in line.split(): 
            if s.isdigit():
                return int(s)
            
    # ----------------------------------------------------------------
    def extractString(self, line):
        str = line.partition('-')[2].strip('\n')
        return str
     
    # ----------------------------------------------------------------
    def extractDate(self, line):
        str = line.partition('-')[2].strip('\n')
        return str
      
     
    # ----------------------------------------------------------------

    def process(self, metaData, contentPath):
        '''
        @see: IMetaDataHandler.process
        '''
        assert isinstance(metaData, MetaDataMapped), 'Invalid meta data %s' % metaData
        try:
            metaData.IsAvailable = True
            metaData.thumbnailFormatId = self._thumbnailFormat.id
            
            jarPath = join('tools', 'media-archive-image', 'metadata_extractor.jar');
            p = subprocess.Popen(['java', '-jar', jarPath, contentPath], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            result = p.wait()
            assert result == 0
            
            imageData = ImageData()      
            imageData.Id = metaData.Id    
            
            while 1:
                line = p.stdout.readline()
                if not line: break   
                line = str(line, "utf-8")
                
                if line.find('Width') != -1:
                    imageData.Width = self.extractNumber(line)
                elif line.find('Height') != -1:
                    imageData.Height = self.extractNumber(line)
                elif line.find('Time Original') != -1:
                    imageData.CreationDate = self.extractString(line)
                elif line.find('Make') != -1:    
                    imageData.CameraMake = self.extractString(line)
                elif line.find('] Model ') != -1:
                    imageData.CameraModel = self.extractString(line)        
        except PathNotFound:
            metaData.IsAvailable = False          
                
        try:
            self.session().add(imageData)
            self.session().add(metaData)
            self.session().flush((imageData, metaData,))    
        except SQLAlchemyError as e: handle(e, imageData)  
        
        self.thumbnailManager.processThumbnail(self._thumbnailFormat.id, contentPath, metaData)
        
        return imageData.Id

    # ----------------------------------------------------------------

    def _typeId(self):
        '''
        Provides the meta type image id. 
        '''
        if self._metaTypeId is None:
            try: metaType = self.session().query(MetaTypeMapped).filter(MetaTypeMapped.Key == self.imageTypeName).one()
            except NoResultFound:
                metaType = MetaTypeMapped()
                metaType.Key = self.imageTypeKey
                self.session().add(metaType)
                self.session().flush((metaType,))
            self._metaTypeId = metaType.id
        return self._metaTypeId

    # ----------------------------------------------------------------

    def deploy(self):
        '''
           Deploy 
        '''
        self._thumbnailFormatGeneric = thumbnailFormatFor(self.session(), '%(size)s/image_generic.jpg')
        referenceLast = self.thumbnailManager.timestampThumbnail(self._thumbnailFormatGeneric.id)
        imagePath = join(pythonPath(), 'resources', 'other.jpg')
        if referenceLast is None or referenceLast < timestampURI(imagePath):
            self.thumbnailManager.processThumbnail(self._thumbnailFormatGeneric.id, imagePath)
            
        self._thumbnailFormat = thumbnailFormatFor(self.session(), '%(size)s/%(id)d.jpg')    
