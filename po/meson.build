gettext_targets = i18n.gettext(
  'quizbite',
  preset: 'glib',
  args: [
    # UI files are generated from Blueprint in the build directory.
    '-D', meson.project_build_root(),
  ],
)

# Convenience maintainer targets that ensure the generated `.ui` files exist
# before xgettext runs.
alias_target('quizbite-pot-full', blueprints, gettext_targets[1])
alias_target('quizbite-update-po-full', blueprints, gettext_targets[2])
