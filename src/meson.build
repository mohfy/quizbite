blueprints = custom_target('blueprints',
  input: files(
    'shortcuts_dialog.blp',
    'ui/window.blp',
    'ui/editor/create_quiz.blp',
  ),
  output: '.',
  command: [
    find_program('blueprint-compiler'),
    'batch-compile',
    '--minify',
    '@OUTPUT@',
    '@CURRENT_SOURCE_DIR@',
    '@INPUT@',
  ],
)

pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'quizbite'
gnome = import('gnome')

gnome.compile_resources('quizbite',
  'quizbite.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: blueprints,
)

python = import('python')

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'quizbite.in',
  output: 'quizbite',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x'
)

quizbite_sources = [
  '__init__.py',
  'main.py',
]

quizbite_ui_sources = [
  'ui/__init__.py',
  'ui/window.py',
  'ui/quiz_library.py',
]

quizbite_ui_editor_sources = [
  'ui/editor/__init__.py',
  'ui/editor/create_quiz.py',
  'ui/editor/create_quiz_support.py',
]

quizbite_ui_play_sources = [
  'ui/play_quiz/__init__.py',
  'ui/play_quiz/quiz_player.py',
  'ui/play_quiz/quiz_session.py',
  'ui/play_quiz/score_view.py',
]

quizbite_ui_utils_sources = [
  'ui/utils/__init__.py',
  'ui/utils/file_dialogs.py',
  'ui/utils/pdfgenerator.py',
]

quizbite_data_sources = [
  'data/__init__.py',
  'data/db.py',
  'data/quiz_file.py',
]

install_data(quizbite_sources, install_dir: moduledir)
install_data(quizbite_ui_sources, install_dir: moduledir / 'ui')
install_data(quizbite_ui_editor_sources, install_dir: moduledir / 'ui' / 'editor')
install_data(quizbite_ui_play_sources, install_dir: moduledir / 'ui' / 'play_quiz')
install_data(quizbite_ui_utils_sources, install_dir: moduledir / 'ui' / 'utils')
install_data(quizbite_data_sources, install_dir: moduledir / 'data')
