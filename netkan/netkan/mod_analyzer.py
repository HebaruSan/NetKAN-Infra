import re
import tempfile
from pathlib import Path
from zipfile import ZipFile, is_zipfile
from typing import Dict, List, Any, Union, Pattern

from .common import download_stream_to_file


class CfgAspect:

    def __init__(self, cfg_regex: str, tags: List[str], depends: List[str]) -> None:
        self.cfg_pattern = re.compile(cfg_regex, re.MULTILINE)
        self.tags = tags
        self.depends = depends

    def analyze(self, analyzer: 'ModAnalyzer') -> None:
        if analyzer.pattern_matches_any_cfg(self.cfg_pattern):
            analyzer.tags += self.tags
            analyzer.depends += [{'name': dep} for dep in self.depends]


class ModAnalyzer:

    ASPECTS: List[CfgAspect] = [
        CfgAspect(r'^\s*[@+$\-!%]|^\s*[a-zA-Z0-9_]+:',
                                            [],               ['ModuleManager']),
        CfgAspect(r'^\s*PART\b',            ['parts'],        []),
        CfgAspect(r'^\s*@TechTree\b',       ['tech-tree'],    []),
        CfgAspect(r'^\s*@Kopernicus\b',     ['planet-pack'],  ['Kopernicus']),
        CfgAspect(r'^\s*STATIC\b',          ['buildings'],    ['KerbalKonstructs']),
        CfgAspect(r'^\s*TUFX_PROFILE\b',    ['graphics'],     ['TUFX']),
        CfgAspect(r'^\s*CONTRACT_TYPE\b',   ['career'],       ['ContractConfigurator']),
        CfgAspect(r'^\s*@CUSTOMBARNKIT\b',  [],               ['CustomBarnKit']),
        CfgAspect(r'^\s*name\s*=\s*ModuleB9PartSwitch\b',
                                            [],               ['B9PartSwitch']),
    ]
    FILTERS = [
        '__MACOSX', '.DS_Store',
        'Thumbs.db',
        '.git', '.gitignore',
    ]
    FILTER_REGEXPS = [
        r'\.mdb$', r'\.pdb$',
        r'~$',
    ]

    def __init__(self, ident: str, download_url: str) -> None:
        self.ident = ident
        self.download_file = tempfile.NamedTemporaryFile()
        download_stream_to_file(download_url, self.download_file)
        self.download_file.flush()
        self.zip = (ZipFile(self.download_file, 'r')
                    if is_zipfile(self.download_file)
                    else None)
        # Dir entries are optional, so try to ignore them
        self.files = ([] if not self.zip else
                      [zi for zi in self.zip.infolist()
                       if not zi.is_dir()])

        self.tags: List[str] = [*(['plugin'] if self.has_dll() else []),
                                *(['config'] if self.has_cfg() else [])]
        self.depends: List[Dict[str, str]] = []
        for aspect in self.ASPECTS:
            aspect.analyze(self)
        if 'parts' in self.tags:
            self.tags.remove('config')

    def has_version_file(self) -> bool:
        return any(zi.filename.lower().endswith('.version')
                   for zi in self.files)

    def has_dll(self) -> bool:
        return any(zi.filename.lower().endswith('.dll')
                   for zi in self.files)

    def has_cfg(self) -> bool:
        return any(zi.filename.lower().endswith('.cfg')
                   for zi in self.files)

    def pattern_matches_any_cfg(self, pattern: Pattern[str]) -> bool:
        return (False if not self.zip
                else any(zi.filename.lower().endswith('.cfg')
                         and pattern.search(
                             self.zip.read(zi.filename).decode('utf8', errors='ignore'))
                         for zi in self.files))

    def has_ident_folder(self) -> bool:
        return any(self.ident in Path(zi.filename).parts[:-1]
                   for zi in self.files)

    def find_folder(self) -> str:
        # First look for a unique entry directly under GameData
        dir_parts = {Path(zi.filename).parts[:-1] for zi in self.files}
        dirs_with_gamedata = {(dirs, dirs.index('GameData'))
                              for dirs in dir_parts
                              if 'GameData' in dirs}
        parts_after_gd = {dirs[i + 1]
                          for dirs, i in dirs_with_gamedata
                          if i < len(dirs) - 1}
        if len(parts_after_gd) > 1:
            # Multiple folders under GameData, manual review required
            return ''
        if len(parts_after_gd) == 1:
            # Found GameData with only one subdir, return it
            return next(iter(parts_after_gd))
        # If no GameData, look for unique folder in root
        first_parts = {dirs[0] for dirs in dir_parts if len(dirs) > 0}
        if len(first_parts) == 1:
            # No GameData but only one root folder, return it
            return next(iter(first_parts))
        # No GameData, multiple folders in root, manual review required
        return ''

    def get_filters(self) -> List[str]:
        return [filt for filt in self.FILTERS
                # Normal filter are case insensitive
                if any(filt.casefold() in Path(zi.filename.casefold()).parts
                       for zi in self.files)]

    def get_filter_regexps(self) -> List[str]:
        return [filt for filt in self.FILTER_REGEXPS
                # Regex filters are case sensitive
                if any(re.search(filt, zi.filename)
                       for zi in self.files)]

    @staticmethod
    def flatten(a_list: List[str]) -> Union[List[str], str]:
        return a_list[0] if len(a_list) == 1 else a_list

    def get_netkan_properties(self) -> Dict[str, Any]:
        props: Dict[str, Any] = { }

        if self.has_version_file():
            props['$vref'] = '#/ckan/ksp-avc'
        props['tags'] = self.tags
        if self.depends:
            props['depends'] = self.depends

        filters = self.get_filters()
        filter_regexps = self.get_filter_regexps()
        if not self.has_ident_folder() or filters or filter_regexps:
            # Can't use default stanza
            props['install'] = [ {
                'find': (self.ident if self.has_ident_folder()
                         else self.find_folder()),
                'install_to': 'GameData'
            } ]
            if filters:
                props['install'][0]['filter'] = ModAnalyzer.flatten(filters)
            if filter_regexps:
                props['install'][0]['filter_regexp'] = ModAnalyzer.flatten(filter_regexps)

        return props
