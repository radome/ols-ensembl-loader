# -*- coding: utf-8 -*-
# @author Marc Chakiachvili

import logging
from os.path import join
from urllib import parse

import eHive

from loader import OlsLoader


class OLSHiveLoader(eHive.BaseRunnable):
    """ OLS MySQL loader runnable class for eHive integration """
    db_base_name = 'ensembl_ontology'
    log_levels = [
        logging.ERROR,
        logging.WARNING,
        logging.INFO,
        logging.DEBUG
    ]
    log_file = 'ols_loader_%s.log'
    ols_loader = None

    def param_defaults(self):
        return {
            'drop_before': True,  # currently not used in pipeline configuration
            'echo': False,
            'verbosity': 0,
            'log_to': 'dev > null'
        }

    def fetch_input(self):
        assert self.param_required('ontology_name') in OlsLoader.ONTOLOGIES_LIST
        # TODO Check db exists
        db_url_parts = parse.urlparse(self.param_required('db_url'))
        assert db_url_parts.scheme in ('mysql')
        assert db_url_parts.path != ''
        if db_url_parts.scheme == 'mysql':
            assert db_url_parts.port != ''
            assert db_url_parts.username != ''
            assert db_url_parts.password != ''
        logging.basicConfig(level=self.log_levels[self.param('verbosity')],
                            format='%(asctime)s %(levelname)s : %(name)s.%(funcName)s(%(lineno)d) - %(message)s',
                            datefmt='%m-%d %H:%M - %s',
                            filename=join(self.param_required('output_dir'),
                                          self.log_file % self.param_required('ontology_name')),
                            filemode='w')

    def run(self):
        # False => erreur marque le job en failed, i.e pas de retry
        self.input_job.transient_error = False
        # TODO add default options
        options = self.param_defaults()
        options['db_version'] = self.param_required('ens_version')
        if self.param_required('drop_before') is False:
            options['wipe'] = False

        self.ols_loader = OlsLoader(self.param_required('db_url'), **options)
        self.ols_loader.init_meta()

    def write_output(self):
        self.ols_loader.load(self.param_required('ontology_name'))
        pass
