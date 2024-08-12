import json
import os
import re
import subprocess
import sys
import tomllib
from operator import itemgetter
from pathlib import Path


def _get_pkg_dir(plugin_dir: Path):
    candidates = list(plugin_dir.glob('indico_*/__init__.py'))
    if len(candidates) == 1:
        return candidates[0].parent
    elif candidates:
        print(f'::error::Found multiple potential plugin package dirs: {candidates}')
        sys.exit(1)
    else:
        if any(plugin_dir.glob('indico_*.py')):
            return None
        print('::error::Found no plugin package dirs and no single-file plugin')
        sys.exit(1)


def _plugin_has_assets(plugin_dir: Path):
    return (plugin_dir / 'webpack.config.js').exists() or (plugin_dir / 'webpack-bundles.json').exists()


def _plugin_has_i18n(plugin_dir: Path):
    if not (pkg_dir := _get_pkg_dir(plugin_dir)):
        return False
    return (pkg_dir / 'translations').exists()


def _get_plugin_deps(plugin_dir: Path):
    reqs = tomllib.loads((plugin_dir / 'pyproject.toml').read_text())['project']['dependencies']
    return [
        re.match(r'indico-plugin-([^>=<]+)', x).group(1).replace('-', '_')
        for x in reqs
        if x.startswith('indico-plugin-')
    ]


def _get_plugin_data(plugin_dir: Path, *, single=False):
    if single:
        name = _get_pkg_dir(plugin_dir).name.removeprefix('indico_')
        meta = False
    else:
        name = plugin_dir.name
        meta = name == '_meta'
    return {
        'plugin': name,
        'path': '' if single else name,
        'install': not meta,
        'assets': _plugin_has_assets(plugin_dir) if not meta else False,
        'i18n': _plugin_has_i18n(plugin_dir) if not meta else False,
        'deps': _get_plugin_deps(plugin_dir) if not meta else [],
        'single': single,
    }


def _get_changed_dirs():
    try:
        resp = subprocess.check_output(
            ['gh', 'api', f'repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{os.environ['PR_NUMBER']}/files',
             '--paginate'],
            encoding='utf-8',
        )
    except subprocess.CalledProcessError:
        print('::error::Could not get changed files')
        sys.exit(1)
    return {x['filename'].split('/')[0] for x in json.loads(resp) if '/' in x['filename']}


def main():
    if Path('pyproject.toml').exists():
        # single-plugin repo
        plugin_data = [_get_plugin_data('..' / Path(Path().absolute().name), single=True)]
    else:
        # multi-plugin repo
        plugin_data = sorted(
            (_get_plugin_data(x) for x in Path().iterdir() if x.is_dir() and (x / 'pyproject.toml').exists()),
            key=itemgetter('plugin'),
        )
        # Filter out untouched plugins if we're running for a PR
        if os.environ['GITHUB_EVENT_NAME'] == 'pull_request':
            print('::notice title=PR mode::Adding plugins touched in this PR to matrix')
            changed_dirs = _get_changed_dirs()
            plugin_data = [x for x in plugin_data if x['plugin'] in changed_dirs]
        elif os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch':
            print('::notice title=Manual mode::Adding all plugins to matrix')
        else:
            print('::notice title=Push mode::Adding all plugins to matrix')

    if plugin_data:
        print(f'::notice title=Plugins added to matrix::{', '.join(sorted(x['plugin'] for x in plugin_data))}')
    else:
        print('::notice::Empty matrix, no plugins found')

    matrix = json.dumps({'include': plugin_data}) if plugin_data else ''
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'matrix={matrix}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
