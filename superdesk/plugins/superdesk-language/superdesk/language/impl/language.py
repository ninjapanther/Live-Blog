'''
Created on Jun 23, 2011

@package superdesk
@copyright 2011 Sourcefabric o.p.s.
@license http://www.gnu.org/licenses/gpl-3.0.txt
@author: Gabriel Nistor

SQL alchemy implementation for language API.
'''

from ..api.language import Language, QLanguage, ILanguageService
from ..meta.language import LanguageEntity
from ally import internationalization
from ally.container import wire
from ally.container.ioc import injected
from ally.exception import InputException, DevelException, Ref
from ally.listener.binder_op import validateProperty
from ally.support.api.util_service import trimIter, likeAsRegex
from babel.core import Locale
from babel.localedata import locale_identifiers
from collections import OrderedDict
from sql_alchemy.impl.entity import EntityNQServiceAlchemy

# --------------------------------------------------------------------

_ = internationalization.translator(__name__)

# --------------------------------------------------------------------

@injected
class LanguageServiceBabelAlchemy(EntityNQServiceAlchemy, ILanguageService):
    '''
    Implementation for @see: ILanguageService using Babel library.
    '''
    
    default_language = 'en'; wire.config('default_language', doc=
    'The default language to use in presenting the languages names')
    
    def __init__(self):
        EntityNQServiceAlchemy.__init__(self, LanguageEntity)
        self._locales = OrderedDict([(code, Locale.parse(code)) for code in locale_identifiers()])
        validateProperty(LanguageEntity.Code, self._validateCode)
    
    def getByCode(self, code, translate):
        '''
        @see: ILanguageService.getByCode
        '''
        if not translate: translate = self.default_language
        locale = self._localeOf(code)
        if not locale: raise InputException(Ref(_('Unknown code'), ref=Language.Code))
        return self._populate(Language(code), self._translator(locale, self._localesOf(translate)))

    def getAllAvailable(self, offset, limit, q, translate):
        '''
        @see: ILanguageService.getAllAvailable
        '''
        if not translate: translate = self.default_language
        locales = self._localesOf(translate)
        if q and QLanguage.name in q and q.name.like:
            assert isinstance(q, QLanguage), 'Invalid query %s' % q
            nameRegex = likeAsRegex(q.name.like)
            languages = []
            for code, locale in self._locales.items():
                translator = self._translator(locale, locales)
                assert isinstance(translator, Locale)
                name = translator.languages.get(locale.language)
                if name and nameRegex.match(name): languages.append((code, translator))
                    
            languages = trimIter(iter(languages), len(languages), offset, limit)
            return (self._populate(Language(code), translator) for code, translator in languages)
        
        languages = trimIter(iter(self._locales.items()), len(self._locales), offset, limit)
        return (self._populate(Language(code), self._translator(locale, locales)) for code, locale in languages)
    
    def getById(self, id, translate):
        '''
        @see: ILanguageService.getById
        '''
        if not translate: translate = self.default_language
        locales = self._localesOf(translate)
        language = super().getById(id)
        return self._populate(language, self._translator(self._localeOf(language.Code), locales))
    
    def getAll(self, offset, limit, translate):
        '''
        @see: ILanguageService.getAll
        '''
        if not translate: translate = self.default_language
        locales = self._localesOf(translate)
        languages = self._getAll(None, offset, limit)
        return (self._populate(language, self._translator(self._localeOf(language.Code), locales))
                for language in languages)
    
    def getCount(self):
        '''
        @see: ILanguageService.getCount
        '''
        return  self._getCount()
    
    # ----------------------------------------------------------------

    def _localeOf(self, code):
        '''
        Helper that parses the code to a babel locale.
        
        @param code: string
            The language code to provide the locale for.
        @return: Locale|None
            The locale for the code or None if the code is not valid.
        '''
        assert isinstance(code, str), 'Invalid code %s' % code
        return self._locales.get(code.replace('-', '_'))
    
    def _localesOf(self, codes):
        '''
        Helper method that based on a language code list will provide a babel locales.
        
        @param codes: string|iter(string)
            The language code to provide the locale for.
        @return: Locale|None
            The locale for the code or None if the code is not valid.
        '''
        if isinstance(codes, str): codes = [codes]
        return list(filter(None, (self._localeOf(code) for code in codes)))

    def _translator(self, locale, locales):
        '''
        Helper method that provides the translated language name for locale 'l' based on the locales list, the first
        locale will be used if not translation will be available for that than it will fall back to the next.
        
        @param locale: Locale
            The locale to get the translator for.
        @param locales: list[Locale]|tuple(Locale)
            The locales to translate the name for.
        @return: Locale
            The translating locale.
        '''
        assert isinstance(locale, Locale), 'Invalid locale %s' % locale
        assert isinstance(locales, (list, tuple)), 'Invalid locales %s' % locales
        for loc in locales:
            assert isinstance(loc, Locale), 'Invalid locale %s' % loc
            if locale.language in loc.languages: return loc
        return locale

    def _populate(self, language, translator):
        '''
        Helper method that populates directly the language with the translation name.
        
        @param language: Language
            The language to be populated with info from the locale.
        @param translator: Locale
            The translating locale to populate from.
        '''
        assert isinstance(language, Language), 'Invalid language %s' % language
        assert isinstance(translator, Locale), 'Invalid translator locale %s' % translator
        
        locale = self._localeOf(language.Code)
        if not locale: raise DevelException('Invalid language code %r' % language.Code)
        
        language.Name = translator.languages.get(locale.language)
        if locale.territory: language.Script = translator.territories.get(locale.territory)
        if locale.script: language.Script = translator.scripts.get(locale.script)
        if locale.variant: language.Script = translator.variants.get(locale.variant)
        
        return language
    
    def _validateCode(self, language, model, prop, errors):
        '''
        Validates the language code on a language instance, this is based on the operator listeners.
        '''
        assert isinstance(language, Language), 'Invalid language %s' % language
        locale = self._localeOf(language.Code) 
        if not locale:
            errors.append(Ref(_('Invalid language code'), ref=Language.Code))
            return False
        else: language.Code = str(locale)
