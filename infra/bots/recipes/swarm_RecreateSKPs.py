# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Recipe for the Skia RecreateSKPs Bot."""


DEPS = [
  'build/file',
  'depot_tools/gclient',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'skia-recipes/core',
  'skia-recipes/infra',
  'skia-recipes/vars',
]


TEST_BUILDERS = {
  'client.skia.compile': {
    'skiabot-linux-swarm-000': [
      'Housekeeper-Nightly-RecreateSKPs_Canary',
      'Housekeeper-Weekly-RecreateSKPs',
    ],
  },
}


UPDATE_SKPS_GITCOOKIES_FILE = 'update_skps.git_cookies'
UPDATE_SKPS_KEY = 'update_skps_git_cookies'


class gitcookies_auth(object):
  """Download update-skps@skia.org's .gitcookies."""
  def __init__(self, api, metadata_key):
    self.m = api
    self._key = metadata_key

  def __enter__(self):
    return self.m.python.inline(
        'download update-skps.gitcookies',
        """
import os
import urllib2

TOKEN_FILE = '%s'
TOKEN_URL = 'http://metadata/computeMetadata/v1/project/attributes/%s'

req = urllib2.Request(TOKEN_URL, headers={'Metadata-Flavor': 'Google'})
contents = urllib2.urlopen(req).read()

home = os.path.expanduser('~')
token_file = os.path.join(home, TOKEN_FILE)

with open(token_file, 'w') as f:
  f.write(contents)
        """ % (UPDATE_SKPS_GITCOOKIES_FILE,
               self._key),
    )

  def __exit__(self, t, v, tb):
    self.m.python.inline(
        'cleanup update-skps.gitcookies',
        """
import os


TOKEN_FILE = '%s'


home = os.path.expanduser('~')
token_file = os.path.join(home, TOKEN_FILE)
if os.path.isfile(token_file):
  os.remove(token_file)
        """ % (UPDATE_SKPS_GITCOOKIES_FILE),
    )
    return v is None


def RunSteps(api):
  # Check out Chrome.
  api.core.setup()

  src_dir = api.vars.checkout_root.join('src')
  out_dir = src_dir.join('out', 'Release')

  # Call GN.
  platform = 'linux64'  # This bot only runs on linux; don't bother checking.
  gn = src_dir.join('buildtools', platform, 'gn')
  api.step('GN',
           [gn, 'gen', out_dir],
           env={'CPPFLAGS': '-DSK_ALLOW_CROSSPROCESS_PICTUREIMAGEFILTERS=1',
                'GYP_GENERATORS': 'ninja'},
           cwd=src_dir)
  # Build Chrome.
  api.step('Build Chrome',
           ['ninja', '-C', out_dir, 'chrome'],
           cwd=src_dir)

  # Clean up the output dir.
  output_dir = api.path['start_dir'].join('skp_output')
  if api.path.exists(output_dir):
    api.file.rmtree('skp_output', output_dir)
  api.file.makedirs('skp_output', output_dir)

  # Capture the SKPs.
  path_var= api.path.pathsep.join([str(api.path['depot_tools']), '%(PATH)s'])
  env = {
      'CHROME_HEADLESS': '1',
      'PATH': path_var,
  }
  asset_dir = api.vars.infrabots_dir.join('assets', 'skp')
  cmd = ['python', asset_dir.join('create.py'),
         '--chrome_src_path', src_dir,
         '--browser_executable', src_dir.join('out', 'Release', 'chrome'),
         '--target_dir', output_dir]
  if 'Canary' not in api.properties['buildername']:
    cmd.append('--upload_to_partner_bucket')
  api.step('Recreate SKPs',
           cmd=cmd,
           cwd=api.vars.skia_dir,
           env=env)

  # Upload the SKPs.
  if 'Canary' not in api.properties['buildername']:
    api.infra.update_go_deps()
    update_skps_gitcookies = api.path.join(api.path.expanduser('~'),
                                           UPDATE_SKPS_GITCOOKIES_FILE)
    cmd = ['python',
           api.vars.skia_dir.join('infra', 'bots', 'upload_skps.py'),
           '--target_dir', output_dir,
           '--gitcookies', str(update_skps_gitcookies)]
    env.update(api.infra.go_env)
    with gitcookies_auth(api, UPDATE_SKPS_KEY):
      api.step('Upload SKPs',
               cmd=cmd,
               cwd=api.vars.skia_dir,
               env=env)


def GenTests(api):
  mastername = 'client.skia.compile'
  slavename = 'skiabot-linux-swarm-000'
  builder = 'Housekeeper-Nightly-RecreateSKPs_Canary'
  yield (
      api.test(builder) +
      api.properties(buildername=builder,
                     mastername=mastername,
                     slavename=slavename,
                     repository='https://skia.googlesource.com/skia.git',
                     revision='abc123',
                     buildnumber=2,
                     path_config='kitchen',
                     swarm_out_dir='[SWARM_OUT_DIR]') +
      api.path.exists(api.path['start_dir'].join('skp_output'))
  )

  builder = 'Housekeeper-Weekly-RecreateSKPs'
  yield (
      api.test(builder) +
      api.properties(buildername=builder,
                     mastername=mastername,
                     slavename=slavename,
                     repository='https://skia.googlesource.com/skia.git',
                     revision='abc123',
                     buildnumber=2,
                     path_config='kitchen',
                     swarm_out_dir='[SWARM_OUT_DIR]') +
      api.path.exists(api.path['start_dir'].join('skp_output'))
  )

  yield (
      api.test('failed_upload') +
      api.properties(buildername=builder,
                     mastername=mastername,
                     slavename=slavename,
                     repository='https://skia.googlesource.com/skia.git',
                     revision='abc123',
                     buildnumber=2,
                     path_config='kitchen',
                     swarm_out_dir='[SWARM_OUT_DIR]') +
      api.path.exists(api.path['start_dir'].join('skp_output')) +
      api.step_data('Upload SKPs', retcode=1)
  )
