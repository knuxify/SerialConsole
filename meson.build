project('serialconsole',
          version: '0.0.1',
    meson_version: '>= 0.56.0',
  default_options: [ 'warning_level=2',
                   ],
)

if get_option('devel')
  app_id = 'com.github.knuxify.SerialConsole.Devel'
  bin_name = 'serialconsole-devel'
  name_suffix = ' (Development)'
else
  app_id = 'com.github.knuxify.SerialConsole'
  bin_name = 'serialconsole'
  name_suffix = ''
endif

i18n = import('i18n')

subdir('data')
subdir('src')
subdir('po')

meson.add_install_script('build-aux/meson/postinstall.py')
