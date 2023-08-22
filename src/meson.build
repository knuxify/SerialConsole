pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
moduledir = join_paths(pkgdatadir, 'serialbowl')
gnome = import('gnome')

gnome.compile_resources('serialbowl',
  'serialbowl.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

python = import('python')

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', join_paths(get_option('prefix'), get_option('localedir')))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'serialbowl.in',
  output: 'serialbowl',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir')
)

serialbowl_sources = [
  '__init__.py',
  'config.py',
  'common.py',
  'main.py',
  'serial.py',
  'window.py',
]

install_data(serialbowl_sources, install_dir: moduledir)
