#!/usr/bin/env python

import glob
import os
import os.path
import sys

if sys.version_info < (3, 6, 0):
    sys.stderr.write("ERROR: You need Python 3.6 or later to use mypy.\n")
    exit(1)

# we'll import stuff from the source tree, let's ensure is on the sys path
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

# This requires setuptools when building; setuptools is not needed
# when installing from a wheel file (though it is still needed for
# alternative forms of installing, as suggested by README.md).
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from mypy.version import __version__ as version, mypy_version

description = 'Based static typing for Python'
long_description = '''
Basedmypy -- Based Static Typing for Python
===========================================

Ever tried to use pythons type system and thought to yourself "This doesn't seem based".

Well fret no longer as basedmypy got you covered!

Baseline
--------

Basedmypy has baseline, baseline is based! It allows you to adopt new features from basedmypy
without the burden of fixing up every usage, just save all current errors to the baseline
file and deal with them later.

.. code-block:: python

    def foo(a):
        print(a)

.. code-block:: bash

    > mypy .
    error: missing typehints !!!!!
    Epic fail bro!

    > mypy --write-baseline .
    error: missing typehints
    Baseline successfully saved!

    > mypy .
    Looks good to me, no errors!
'''.lstrip()


def find_package_data(base, globs, root='mypy'):
    """Find all interesting data files, for setup(package_data=)

    Arguments:
      root:  The directory to search in.
      globs: A list of glob patterns to accept files.
    """

    rv_dirs = [root for root, dirs, files in os.walk(base)]
    rv = []
    for rv_dir in rv_dirs:
        files = []
        for pat in globs:
            files += glob.glob(os.path.join(rv_dir, pat))
        if not files:
            continue
        rv.extend([os.path.relpath(f, root) for f in files])
    return rv


class CustomPythonBuild(build_py):
    def pin_version(self):
        path = os.path.join(self.build_lib, 'mypy')
        self.mkpath(path)
        with open(os.path.join(path, 'version.py'), 'w') as stream:
            stream.write('__version__ = "{}"\n'.format(version))
            stream.write('mypy_version = "{}"\n'.format(mypy_version))

    def run(self):
        self.execute(self.pin_version, ())
        build_py.run(self)


cmdclass = {'build_py': CustomPythonBuild}

package_data = ['py.typed']

package_data += find_package_data(os.path.join('mypy', 'typeshed'), ['*.py', '*.pyi'])
package_data += [os.path.join('mypy', 'typeshed', 'stdlib', 'VERSIONS')]

package_data += find_package_data(os.path.join('mypy', 'xml'), ['*.xsd', '*.xslt', '*.css'])

USE_MYPYC = False
# To compile with mypyc, a mypyc checkout must be present on the PYTHONPATH
if len(sys.argv) > 1 and sys.argv[1] == '--use-mypyc':
    sys.argv.pop(1)
    USE_MYPYC = True
if os.getenv('MYPY_USE_MYPYC', None) == '1':
    USE_MYPYC = True

if USE_MYPYC:
    MYPYC_BLACKLIST = tuple(os.path.join('mypy', x) for x in (
        # Need to be runnable as scripts
        '__main__.py',
        'pyinfo.py',
        os.path.join('dmypy', '__main__.py'),

        # Uses __getattr__/__setattr__
        'split_namespace.py',

        # Lies to mypy about code reachability
        'bogus_type.py',

        # We don't populate __file__ properly at the top level or something?
        # Also I think there would be problems with how we generate version.py.
        'version.py',

        # Skip these to reduce the size of the build
        'stubtest.py',
        'stubgenc.py',
        'stubdoc.py',
        'stubutil.py',
    )) + (
        # Don't want to grab this accidentally
        os.path.join('mypyc', 'lib-rt', 'setup.py'),
    )

    everything = (
        [os.path.join('mypy', x) for x in find_package_data('mypy', ['*.py'])] +
        [os.path.join('mypyc', x) for x in find_package_data('mypyc', ['*.py'], root='mypyc')])
    # Start with all the .py files
    all_real_pys = [x for x in everything
                    if not x.startswith(os.path.join('mypy', 'typeshed') + os.sep)]
    # Strip out anything in our blacklist
    mypyc_targets = [x for x in all_real_pys if x not in MYPYC_BLACKLIST]
    # Strip out any test code
    mypyc_targets = [x for x in mypyc_targets
                     if not x.startswith((os.path.join('mypy', 'test') + os.sep,
                                          os.path.join('mypyc', 'test') + os.sep,
                                          os.path.join('mypyc', 'doc') + os.sep,
                                          os.path.join('mypyc', 'test-data') + os.sep,
                                          ))]
    # ... and add back in the one test module we need
    mypyc_targets.append(os.path.join('mypy', 'test', 'visitors.py'))

    # The targets come out of file system apis in an unspecified
    # order. Sort them so that the mypyc output is deterministic.
    mypyc_targets.sort()

    use_other_mypyc = os.getenv('ALTERNATE_MYPYC_PATH', None)
    if use_other_mypyc:
        # This bit is super unfortunate: we want to use a different
        # mypy/mypyc version, but we've already imported parts, so we
        # remove the modules that we've imported already, which will
        # let the right versions be imported by mypyc.
        del sys.modules['mypy']
        del sys.modules['mypy.version']
        del sys.modules['mypy.git']
        sys.path.insert(0, use_other_mypyc)

    from mypyc.build import mypycify
    opt_level = os.getenv('MYPYC_OPT_LEVEL', '3')
    debug_level = os.getenv('MYPYC_DEBUG_LEVEL', '1')
    force_multifile = os.getenv('MYPYC_MULTI_FILE', '') == '1'
    ext_modules = mypycify(
        mypyc_targets + ['--config-file=mypy_bootstrap.ini'],
        opt_level=opt_level,
        debug_level=debug_level,
        # Use multi-file compilation mode on windows because without it
        # our Appveyor builds run out of memory sometimes.
        multi_file=sys.platform == 'win32' or force_multifile,
    )
else:
    ext_modules = []


classifiers = [
    'Development Status :: 4 - Beta',
    'Environment :: Console',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: MIT License',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.6',
    'Programming Language :: Python :: 3.7',
    'Programming Language :: Python :: 3.8',
    'Programming Language :: Python :: 3.9',
    'Programming Language :: Python :: 3.10',
    'Topic :: Software Development',
]

setup(name='basedmypy',
      version=version,
      description=description,
      long_description=long_description,
      author='KotlinIsland',
      author_email='AMONGUS@pizzahut.com',
      url='https://www.github.com/KotlinIsland/basedmypy',
      license='MIT License',
      py_modules=[],
      ext_modules=ext_modules,
      packages=find_packages(),
      package_data={'mypy': package_data},
      entry_points={'console_scripts': ['mypy=mypy.__main__:console_entry',
                                        'stubgen=mypy.stubgen:main',
                                        'stubtest=mypy.stubtest:main',
                                        'dmypy=mypy.dmypy.client:console_entry',
                                        'mypyc=mypyc.__main__:main',
                                        ]},
      classifiers=classifiers,
      cmdclass=cmdclass,
      # When changing this, also update mypy-requirements.txt.
      install_requires=["typed_ast >= 1.4.0, < 2; python_version<'3.8'",
                        'typing_extensions>=3.10',
                        'mypy_extensions >= 0.4.3',
                        'tomli>=1.1.0',
                        ],
      # Same here.
      extras_require={'dmypy': 'psutil >= 4.0', 'python2': 'typed_ast >= 1.4.0, < 2'},
      python_requires=">=3.6",
      include_package_data=True,
      project_urls={
          'News': 'https://github.com/KotlinIsland/basedmypy/releases',
          'Documentation': 'https://mypy.readthedocs.io/en/stable/introduction.html',
          'Repository': 'https://github.com/KotlinIsland/basedmypy',
      },
      )
