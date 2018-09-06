#  -*- coding: utf-8 -*-

import ebi.ols.api.helpers as helpers
from bio.ensembl.ontology.db import *
from bio.ensembl.ontology.models import *
from ebi.ols.api.client import OlsClient

logger = logging.getLogger(__name__)


class OlsLoader(object):
    """ class loader for mapping retrieved DTO from OLS client into expected database fields """
    __class_map = {
        helpers.Ontology: Ontology,
        helpers.Term: Term,
        helpers.Subset: Subset,
    }

    __relation_map = {
        'parents': 'is_a',
    }

    # TODO check PBQ, FYPO-EXTENSION, FYPO_GO
    ONTOLOGIES_LIST = ['go', 'so', 'pato', 'hpo', 'vt', 'efo', 'po', 'eo', 'to', 'chebi', 'pro', 'fypo',
                       'peco', 'bfo', 'bto', 'cl', 'cmo', 'eco', 'mp', 'ogms', 'uo']  # PBQ? FROM old script order

    _session = None

    def __init__(self, url, **options):
        self.db_url = url
        self.options = options
        self.client = OlsClient()
        dal.db_init(self.db_url, **options)

    @property
    def session(self):
        return dal.get_session()

    def get_or_create(self, model, create_method='', create_method_kwargs=None, **kwargs):
        return get_one_or_create(model, create_method, create_method_kwargs, **kwargs)

    def load(self, ontology_name='all'):
        if ontology_name != 'all':
            m_ontology = self.load_ontology(ontology_name)
            self.load_ontology_terms(m_ontology)
        else:
            # run process for all defaults ontologies setup
            # TODO LOAD META on process start
            for ontology in self.ONTOLOGIES_LIST:
                m_ontology = self.load_ontology(ontology)
                self.load_ontology_terms(m_ontology)

    def load_ontology(self, ontology_name, namespace=None):
        o_ontology = self.client.ontology(ontology_name)
        m_ontology, created = self.get_or_create(Ontology, name=o_ontology.ontology_id,
                                                 namespace=namespace or o_ontology.namespace,
                                                 create_method_kwargs={'helper': o_ontology})
        logger.info('Loaded ontology %s', m_ontology)
        return m_ontology

    @staticmethod
    def wipe_ontology(ontology_name):
        with dal.session_scope() as session:
            try:
                logger.debug('Delete ontology %s', ontology_name)
                ontologies = session.query(Ontology).filter_by(name=ontology_name)
                for ontology in ontologies:
                    OlsLoader.wipe_terms(ontology.id)
                ontologies.delete()
                session.flush()
                return True
            except NoResultFound:
                logger.debug('Ontology not found')
        return False

        # TODO for ontology name, load all relations for all inserted terms

    @staticmethod
    def wipe_terms(ontology, namespace=None):
        with dal.session_scope() as session:
            if type(ontology) is int:
                m_ontology = session.query(Ontology).get(ontology)
            elif type(ontology) is str:
                m_ontology = session.query(Ontology).filter_by(name=ontology, namespace=namespace or ontology).one()
            elif isinstance(ontology, Ontology):
                m_ontology = ontology
            else:
                raise RuntimeError('Wrong parameter')
            try:
                terms = session.query(Term).filter_by(ontology=m_ontology)
                # FIXME delete all related at once avoid loop over terms
                terms.delete()
                return True
            except NoResultFound as e:
                logger.debug('Not found %s', e)
            return False

    def load_term_relations(self, m_term, relation_type):
        rel_name = self.__relation_map.get(relation_type.name, relation_type.name)
        logger.info('   Loading %s relation %s ...', m_term.accession, rel_name)
        o_term = helpers.Term(ontology_name=m_term.ontology.name, iri=m_term.iri)
        o_relatives = o_term.load_relation(relation_type.name)
        logger.info('   %s related terms ', len(o_relatives))
        n_relations = 0
        for o_related in o_relatives:
            if o_related.accession is not None:
                if o_related.is_defining_ontology:
                    if o_related.ontology_name == m_term.ontology.name:
                        r_ontology = m_term.ontology
                    else:
                        logger.info('   The term %s does not belong to current ontology %s', o_related.accession,
                                    m_term.ontology.name)
                        ro_term = self.client.term(identifier=o_related.iri, unique=True)
                        if ro_term is not None and ro_term.ontology_name in self.ONTOLOGIES_LIST:
                            logger.debug('  Term is defined in another expected ontology: %s', ro_term.ontology_name)
                            # load ontology
                            o_onto_details = self.client.ontology(ro_term.ontology_name)
                            r_ontology, created = self.get_or_create(Ontology, name=o_onto_details.ontology_id,
                                                                     namespace=ro_term.obo_name_space,
                                                                     create_method_kwargs=dict(
                                                                         version=o_onto_details.version,
                                                                         title=o_onto_details.title))
                        else:
                            r_ontology = None
                    if r_ontology is not None:
                        m_related, created = self.get_or_create(Term,
                                                                accession=o_related.obo_id,
                                                                create_method_kwargs=dict(
                                                                    helper=o_related,
                                                                    ontology=r_ontology,
                                                                ))
                        # FIXME what to do when term listed in onto is not from this onto ?
                        # m_related = self.load_term(o_related.iri)
                        relation, r_created = self.get_or_create(Relation,
                                                                 child_term=m_related,
                                                                 parent_term=m_term,
                                                                 relation_type=relation_type,
                                                                 ontology=m_term.ontology)
                        n_relations += 1 if r_created else None
                        logger.info('Loaded relation %s %s %s', m_term.accession, rel_name, m_related.accession)
            else:
                logger.warning('This term is not in current ontology, neither defining one %s', o_related)
        logger.info('   ... Done')
        return n_relations

    def _load_term_synonyms(self, o_term):
        logger.info('   Loading term synonyms...')
        session = self.session
        session.query(Synonym).filter(Synonym.term_id == o_term.obo_id).delete()
        m_term = session.query(Term).filter_by(accession=o_term.obo_id).one()
        n_synonyms = 0
        synonym_map = {
            'hasExactSynonym': 'EXACT',
            'hasBroadSynonym': 'BROAD',
            'hasNarrowSynonym': 'NARROW',
            'hasRelatedSynonym': 'RELATED'
        }
        if o_term.obo_synonym:
            for synonym in o_term.obo_synonym:
                if isinstance(synonym, dict):
                    logger.info('   Term synonym %s - %s', synonym['name'], synonym_map[synonym['scope']])
                    db_xref = synonym['xrefs'][0]['database'] + ':' + synonym['xrefs'][0]['id'] \
                        if 'xrefs' in synonym and len(synonym['xrefs']) > 0 else ''
                    m_syno, created = self.get_or_create(Synonym, term=m_term, name=synonym['name'],
                                                         create_method_kwargs=dict(
                                                             db_xref=db_xref,
                                                             type=synonym_map[synonym['scope']]))
                    n_synonyms += 1 if created else None
        logger.info('   ... Done')

    def load_ontology_terms(self, ontology):
        # todo delete current terms ?
        nb_terms = 0
        if type(ontology) is str:
            m_ontology = self.load_ontology(ontology)
            terms = self.client.ontology(ontology).terms()
        elif isinstance(ontology, Ontology):
            m_ontology = ontology
            terms = self.client.ontology(ontology.name).terms()
        elif isinstance(ontology, helpers.Ontology):
            m_ontology = Ontology(helper=ontology)
            terms = ontology.terms()
        else:
            raise RuntimeError('Wrong parameter')
        logger.info('Loading %s terms for %s', len(terms), m_ontology.name)
        for o_term in terms:
            if o_term.is_defining_ontology and o_term.obo_id:
                logger.debug('Loaded term (from OLS) %s', o_term)
                ontology, created = self.get_or_create(Ontology, name=m_ontology.name,
                                                       namespace=o_term.obo_name_space or m_ontology.name,
                                                       create_method_kwargs=dict(
                                                           version=m_ontology.version,
                                                           title=m_ontology.title))
                self.load_term(o_term, ontology)
                nb_terms += 1
        return nb_terms

    def load_term(self, o_term, m_ontology):
        logger.debug('Adding/Retrieving namespaced ontology %s', o_term.obo_name_space)
        m_term, created = self.get_or_create(Term, accession=o_term.obo_id,
                                             create_method_kwargs=dict(helper=o_term,
                                                                       ontology=m_ontology))
        if created:
            logger.info('Create term %s ...', m_term)
            self.load_term_subsets(m_term)
            for relation in o_term.relations_types:
                # updates relation types
                relation_type, created = self.get_or_create(RelationType, name=relation)
                self.load_term_relations(m_term, relation_type)
            self._load_term_synonyms(o_term)
            for alt_id in o_term.annotation.has_alternative_id:
                logger.info('Loaded AltId %s', alt_id)
                m_term.alt_accession.append(AltId(accession=alt_id))
            logger.info('... Done')
        return m_term

    def load_term_subsets(self, term: Term):
        subsets = 0
        logger.info('   Loading term subsets')
        for subset_name in term.subsets.split(','):
            logger.debug('      Processing subset %s', subset_name)
            search = self.client.search(query=subset_name, filters={'ontology': term.ontology.name,
                                                                    'type': 'property'})
            if len(search) == 1:
                details = self.client.detail(search[0])
                subset, created = self.get_or_create(Subset, name=subset_name,
                                                     definition=details.definition or '')
                if created:
                    logger.info('      Created subset [%s: %s]', subset.subset_id, subset_name)
                    subsets += 1
        logger.info('   ... Done')
        return subsets

    def _term_api(self, iri, ontology_name=None, unique=True):
        if ontology_name is not None:
            return self.client.detail(ontology_name=ontology_name, iri=iri, item=helpers.Term, unique=unique)
        else:
            return self.client.term(identifier=iri, unique=True, silent=True)

    def _term_object(self, o_term: helpers.Term):
        m_ontology = self._load_ontology_model(o_term.ontology_name)
        m_term, created = self.get_or_create(Term, accession=o_term.accession,
                                             create_method_kwargs=dict(ontology=m_ontology,
                                                                       helper=o_term))
        return m_term
