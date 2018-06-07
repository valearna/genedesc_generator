import gzip
import json
import tarfile
import urllib.request
import shutil
import os
import re
from enum import Enum
from abc import ABCMeta, abstractmethod
from collections import namedtuple
from typing import List, Iterable, Dict
from ontobio import AssociationSetFactory
from genedescriptions.descriptions_rules import SingleDescStats, set_all_depths_in_subgraph
from ontobio.ontol_factory import OntologyFactory
from ontobio.ontol import Ontology
from ontobio.assocmodel import AssociationSet
from ontobio.io.gafparser import GafParser

Gene = namedtuple('Gene', ['id', 'name', 'dead', 'pseudo'])


class DataType(Enum):
    GO = 1
    DO = 2


class DataFetcher(metaclass=ABCMeta):
    """retrieve data for gene descriptions from different sources"""

    @abstractmethod
    def __init__(self, go_relations: List[str] = None, do_relations: List[str] = None, use_cache: bool = False):
        """create a new a data fetcher

        Args:
            go_relations (List[str]): list of ontology relations to be used for GO
            do_relations (List[str]): list of ontology relations to be used for DO
            use_cache (bool): whether to use cached files
        """
        self.go_associations: AssociationSet = None
        self.go_ontology: Ontology = None
        self.do_ontology: Ontology = None
        self.do_associations: AssociationSet = None
        self.gene_data: Dict[str, Gene] = None
        self.go_relations = go_relations
        self.do_relations = do_relations
        self.use_cache = use_cache

    def _get_cached_file(self, cache_path: str, file_source_url):
        if not os.path.isfile(cache_path):
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            urllib.request.urlretrieve(file_source_url, cache_path)
        elif not self.use_cache:
            urllib.request.urlretrieve(file_source_url, cache_path)
        file_path = cache_path
        if cache_path.endswith(".gz"):
            with gzip.open(cache_path, 'rb') as f_in, open(cache_path.replace(".gz", ""), 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            file_path = cache_path.replace(".gz", "")
        return file_path

    def get_gene_data(self, include_dead_genes: bool = False, include_pseudo_genes: bool = False) -> Gene:
        """get all gene data from the fetcher, returning one gene per call

        Args:
            include_dead_genes (bool): whether to include dead genes in the results
            include_pseudo_genes (bool): whether to include pseudo genes in the results
        Returns:
            Gene: data for one gene per each call, including gene_id and gene_name
        """
        if self.gene_data and len(self.gene_data) > 0:
            for gene_id, gene_obj in self.gene_data.items():
                if (include_dead_genes or not gene_obj.dead) and (include_pseudo_genes or not gene_obj.pseudo):
                    yield gene_obj

    @staticmethod
    def remove_blacklisted_annotations(association_set: AssociationSet, ontology: Ontology,
                                       terms_blacklist) -> AssociationSet:
        """remove annotations linked to blacklisted ontology terms from an association set

        Args:
            association_set (AssociationSet): the original association set
            ontology (Ontology): the ontology linked to the annotations
            terms_blacklist (List[str]): the list of ontology terms related to the annotations to be removed
        Returns:
            AssociationSet: the filtered annotations
        """
        associations = []
        for subj_associations in association_set.associations_by_subj.values():
            for association in subj_associations:
                if association["object"]["id"] not in terms_blacklist:
                    associations.append(association)
        return AssociationSetFactory().create_from_assocs(assocs=associations, ontology=ontology)

    @staticmethod
    def rename_ontology_terms(ontology: Ontology, terms_replacement_regex: Dict[str, str]) -> None:
        """rename ontology terms based on regular expression matching

        Args:
            ontology (Ontology): the ontology containing the terms to be renamed
            terms_replacement_regex (Dict[str, str]): a dictionary containing the regular expression to be applied for
                renaming terms. Each key must be a regular expression to search for terms and the associated value
                another regular expression that defines the final result
        """
        for regex_to_substitute, regex_target in terms_replacement_regex.items():
            for node in ontology.search(regex_to_substitute, is_regex=True):
                ontology.node(node)["label"] = re.sub(regex_to_substitute, regex_target, ontology.node(node)["label"])

    def set_ontology(self, ontology_type: DataType, ontology: Ontology,
                     terms_replacement_regex: Dict[str, str]) -> None:
        """set the go ontology and apply terms renaming

        Args:
            ontology_type (DataType): the type of ontology to set
            ontology (Ontology): an ontology object to set as go ontology
            terms_replacement_regex (Dict[str, str]): a dictionary containing the regular expression to be applied for
                renaming terms. Each key must be a regular expression to search for terms and the associated value
                another regular expression that defines the final result
        """
        new_ontology = None
        if ontology_type == DataType.GO:
            self.go_ontology = ontology.subontology(relations=self.go_relations)
            new_ontology = self.go_ontology
        elif ontology_type == DataType.DO:
            self.do_ontology = ontology.subontology(relations=self.do_relations)
            new_ontology = self.do_ontology
        self.rename_ontology_terms(ontology=new_ontology, terms_replacement_regex=terms_replacement_regex)
        for root_id in new_ontology.get_roots():
            set_all_depths_in_subgraph(ontology=new_ontology, root_id=root_id, relations=None)

    def load_ontology_from_file(self, ontology_type: DataType, ontology_url: str, ontology_cache_path: str,
                                terms_replacement_regex: Dict[str, str] = None) -> None:
        """load go ontology from file

        Args:
            ontology_type (DataType): the type of ontology to set
            ontology_url (str): url to the ontology file
            ontology_cache_path (str): path to cache file for the ontology
            terms_replacement_regex (Dict[str, str])]: a dictionary containing the regular expression to be applied for
                renaming terms. Each key must be a regular expression to search for terms and the associated value
                another regular expression that defines the final result
        """
        new_ontology = None
        if ontology_type == DataType.GO:
            self.go_ontology = OntologyFactory().create(self._get_cached_file(file_source_url=ontology_url,
                                                                              cache_path=ontology_cache_path)
                                                        ).subontology(relations=self.go_relations)
            new_ontology = self.go_ontology
        elif ontology_type == DataType.DO:
            self.do_ontology = OntologyFactory().create(self._get_cached_file(file_source_url=ontology_url,
                                                                              cache_path=ontology_cache_path)
                                                        ).subontology(relations=self.do_relations)
            new_ontology = self.do_ontology
        if terms_replacement_regex:
            self.rename_ontology_terms(ontology=new_ontology, terms_replacement_regex=terms_replacement_regex)
        for root_id in new_ontology.get_roots():
            set_all_depths_in_subgraph(ontology=new_ontology, root_id=root_id, relations=None)

    def set_associations(self, associations_type: DataType, associations: AssociationSet,
                         exclusion_list: List[str]) -> None:
        """set the go annotations and remove blacklisted annotations

        Args:
            associations_type (DataType): the type of associations to set
            associations (AssociationSet): an association object to set as go annotations
            exclusion_list (List[str]): the list of ontology terms related to the annotations to be removed
        """
        if associations_type == DataType.GO:
            self.go_associations = self.remove_blacklisted_annotations(association_set=associations,
                                                                       ontology=self.go_ontology,
                                                                       terms_blacklist=exclusion_list)
        elif associations_type == DataType.DO:
            self.do_associations = self.remove_blacklisted_annotations(association_set=associations,
                                                                       ontology=self.do_ontology,
                                                                       terms_blacklist=exclusion_list)

    def load_associations_from_file(self, associations_type: DataType, associations_url: str,
                                    associations_cache_path: str, exclusion_list: List[str]) -> None:
        """load go associations from file

        Args:
            associations_type (DataType): the type of associations to set
            associations_url (str): url to the association file
            associations_cache_path (str): path to cache file for the associations
            exclusion_list (List[str]): the list of ontology terms related to the annotations to be removed
        """
        if associations_type == DataType.GO:
            self.go_associations = AssociationSetFactory().create_from_assocs(assocs=GafParser().parse(
                file=self._get_cached_file(cache_path=associations_cache_path, file_source_url=associations_url),
                skipheader=True), ontology=self.go_ontology)
            self.go_associations = self.remove_blacklisted_annotations(association_set=self.go_associations,
                                                                       ontology=self.go_ontology,
                                                                       terms_blacklist=exclusion_list)
        elif associations_type == DataType.DO:
            self.do_associations = AssociationSetFactory().create_from_assocs(assocs=GafParser().parse(
                file=self._get_cached_file(cache_path=associations_cache_path, file_source_url=associations_url),
                skipheader=True), ontology=self.do_ontology)
            self.do_associations = self.remove_blacklisted_annotations(association_set=self.do_associations,
                                                                       ontology=self.do_ontology,
                                                                       terms_blacklist=exclusion_list)

    def get_annotations_for_gene(self, gene_id: str, annot_type: DataType = DataType.GO,
                                 include_obsolete: bool = False, include_negative_results: bool = False,
                                 priority_list: Iterable = ("EXP", "IDA", "IPI", "IMP", "IGI", "IEP", "IC", "ISS",
                                                            "ISO", "ISA", "ISM", "IGC", "IBA", "IBD", "IKR", "IRD",
                                                            "RCA", "IEA"),
                                 desc_stats: SingleDescStats = None) -> List[Dict]:
        """
        retrieve go annotations for a given gene id and a given type. The annotations are unique for each pair
        <gene_id, term_id>. This means that when multiple annotations for the same pair are found in the go data, the
        one with the evidence code with highest priority is returned (see the *priority_list* parameter to set the
        priority according to evidence codes)

        Args:
            gene_id (str): the id of the gene related to the annotations to retrieve, in standard format
            annot_type (DataType): type of annotations to read
            include_obsolete (bool): whether to include obsolete annotations
            include_negative_results (bool): whether to include negative results
            priority_list (List[str]): the priority list for the evidence codes. If multiple annotations with the same
                term are found, only the one with highest priority is returned. The first element in the list has the
                highest priority, whereas the last has the lowest. Only annotations with evidence codes in the priority
                list are returned. All other annotations are ignored
            desc_stats (SingleDescStats): an object containing the description statistics where to save the total number
                of annotations for the gene
        Returns:
            List[Dict]: the list of annotations for the given gene
        """
        dataset = None
        ontology = None
        if annot_type == DataType.GO:
            dataset = self.go_associations
            ontology = self.go_ontology
        elif annot_type == DataType.DO:
            dataset = self.do_associations
            ontology = self.do_ontology
        priority_map = dict(zip(priority_list, reversed(range(len(list(priority_list))))))
        annotations = [annotation for annotation in dataset.associations(gene_id) if (include_obsolete or
                                                                                      not ontology.is_obsolete(
                                                                                          annotation["object"]["id"]))
                       and (include_negative_results or "NOT" not in annotation["qualifiers"])]
        if desc_stats:
            desc_stats.total_num_go_annotations = len(annotations)
        id_selected_annotation = {}
        for annotation in annotations:
            if annotation["evidence"]["type"] in priority_map.keys():
                if annotation["object"]["id"] in id_selected_annotation:
                    if priority_map[annotation["evidence"]["type"]] > \
                            priority_map[id_selected_annotation[annotation["object"]["id"]]["evidence"]["type"]]:
                        id_selected_annotation[annotation["object"]["id"]] = annotation
                else:
                    id_selected_annotation[annotation["object"]["id"]] = annotation
        if desc_stats:
            desc_stats.num_prioritized_go_annotations = len(id_selected_annotation.keys())
        return [annotation for annotation in id_selected_annotation.values()]

    def set_gene_data(self, gene_data: List[Gene]):
        for gene in gene_data:
            self.gene_data[gene.id] = gene

    @abstractmethod
    def load_gene_data_from_file(self):
        pass


class WBDataFetcher(DataFetcher):
    """data fetcher for WormBase raw files for a single species"""

    def __init__(self, raw_files_source: str, cache_location: str, release_version: str, species: str, project_id: str,
                 go_relations: List[str] = None, do_relations: List[str] = None, use_cache: bool = False):
        """create a new data fetcher for WormBase. Files will be downloaded from WB ftp site. For convenience, file
        locations are automatically generated and stored in class variables ending in _url for remote filed and
        _cache_path for caching

        Args:
            raw_files_source (str): base url where to fetch the raw files
            cache_location (str): path to cache directory
            release_version (str): WormBase release version for the input files
            species (str): WormBase species to fetch
            project_id (str): project id associated with the species
        """
        super().__init__(go_relations=go_relations, do_relations=do_relations, use_cache=use_cache)
        self.gene_data_cache_path = os.path.join(cache_location, "wormbase", release_version, "species", species,
                                                 project_id, "annotation", species + '.' + project_id +
                                                 '.' + release_version + ".geneIDs.txt.gz")
        self.gene_data_url = raw_files_source + '/' + release_version + '/species/' + species + '/' + project_id + \
                             '/annotation/' + species + '.' + project_id + '.' + release_version + '.geneIDs.txt.gz'
        self.go_ontology_cache_path = os.path.join(cache_location, "wormbase", release_version, "ONTOLOGY",
                                                   "gene_ontology." + release_version + ".obo")
        self.go_ontology_url = raw_files_source + '/' + release_version + '/ONTOLOGY/gene_ontology.' + \
                               release_version + '.obo'
        self.go_associations_cache_path = os.path.join(cache_location, "wormbase", release_version, "species", species,
                                                       project_id, "annotation", species + '.' + project_id + '.' +
                                                       release_version + ".go_annotations.gaf.gz")
        self.go_associations_url = raw_files_source + '/' + release_version + '/species/' + species + '/' + \
                                   project_id + '/annotation/' + species + '.' + project_id + '.' + release_version + \
                                  '.go_annotations.gaf.gz'
        self.do_ontology_url = raw_files_source + '/' + release_version + '/ONTOLOGY/disease_ontology.' + \
                               release_version + '.obo'
        self.do_ontology_cache_path = os.path.join(cache_location, "wormbase", release_version, "ONTOLOGY",
                                                   "disease_ontology." + release_version + ".obo")
        self.do_associations_cache_path = os.path.join(cache_location, "wormbase", release_version, "species", species,
                                                       project_id, "annotation", species + '.' + project_id + '.' +
                                                       release_version + ".do_annotations.wb")
        self.do_associations_url = raw_files_source + '/' + release_version + '/ONTOLOGY/disease_association.' + \
                                   release_version + '.wb'
        self.do_associations_new_cache_path = os.path.join(cache_location, "wormbase", release_version, "species",
                                                           species, project_id, "annotation", species + '.' +
                                                           project_id + '.' + release_version +
                                                          ".do_annotations.daf.txt")
        self.do_associations_new_url = raw_files_source + '/' + release_version + '/ONTOLOGY/disease_association.' + \
                                       release_version + '.daf.txt'

    def load_gene_data_from_file(self) -> None:
        """load gene list from pre-set file location"""
        if not self.gene_data or len(self.gene_data.items()) == 0:
            self.gene_data = {}
            file_path = self._get_cached_file(cache_path=self.gene_data_cache_path, file_source_url=self.gene_data_url)
            with open(file_path) as file:
                for line in file:
                    fields = line.strip().split(',')
                    name = fields[2] if fields[2] != '' else fields[3]
                    self.gene_data["WB:" + fields[1]] = Gene("WB:" + fields[1], name, fields[4] == "Dead", False)

    def load_associations_from_file(self, associations_type: DataType, associations_url: str,
                                    associations_cache_path: str, exclusion_list: List[str]) -> None:
        if associations_type == DataType.GO:
            super().load_associations_from_file(associations_type=associations_type, associations_url=associations_url,
                                                associations_cache_path=associations_cache_path,
                                                exclusion_list=exclusion_list)
        elif associations_type == DataType.DO:
            self.do_associations = AssociationSetFactory().create_from_assocs(
                assocs=GafParser().parse(file=self._get_cached_file(cache_path=self.do_associations_cache_path,
                                                                    file_source_url=self.do_associations_url),
                                         skipheader=True),
                ontology=self.do_ontology)
            associations = []
            for subj_associations in self.do_associations.associations_by_subj.values():
                for association in subj_associations:
                    if association["evidence"]["type"] == "IEA":
                        associations.append(association)
            file_path = self._get_cached_file(cache_path=self.do_associations_new_cache_path,
                                              file_source_url=self.do_associations_new_url)
            header = True
            for line in open(file_path):
                if not line.strip().startswith("!"):
                    if not header:
                        linearr = line.strip().split("\t")
                        if self.do_ontology.node(linearr[10]) and linearr[16] != "IEA":
                            associations.append({"source_line": line,
                                                 "subject": {
                                                     "id": linearr[2],
                                                     "label": linearr[3],
                                                     "type": line[1],
                                                     "fullname": "",
                                                     "synonyms": [],
                                                     "taxon": {"id": linearr[0]}

                                                 },
                                                 "object": {
                                                     "id": linearr[10],
                                                     "taxon": ""
                                                 },
                                                 "qualifiers": linearr[9].split("|"),
                                                 "aspect": "D",
                                                 "relation": {"id": None},
                                                 "negated": False,
                                                 "evidence": {
                                                     "type": linearr[16],
                                                     "has_supporting_reference": linearr[18].split("|"),
                                                     "with_support_from": [],
                                                     "provided_by": linearr[20],
                                                     "date": linearr[19]
                                                     }
                                                 })
                    else:
                        header = False
            self.do_associations = AssociationSetFactory().create_from_assocs(assocs=associations,
                                                                              ontology=self.do_ontology)
            self.do_associations = self.remove_blacklisted_annotations(association_set=self.do_associations,
                                                                       ontology=self.do_ontology,
                                                                       terms_blacklist=exclusion_list)

    def load_all_data_from_file(self, go_terms_replacement_regex: Dict[str, str] = None,
                                go_terms_exclusion_list: List[str] = None,
                                do_terms_replacement_regex: Dict[str, str] = None,
                                do_terms_exclusion_list: List[str] = None) -> None:
        """load all data types from pre-set file locations

        Args:
            go_terms_replacement_regex (Dict[str, str]): a dictionary containing the regular expression to be applied
                for renaming terms. Each key must be a regular expression to search for terms and the associated value
                another regular expression that defines the final result
            go_terms_exclusion_list (List[str]): the list of GO ontology terms related to the GO annotations to be
                removed
            do_terms_replacement_regex (Dict[str, str]): a dictionary containing the regular expression to be applied
                for renaming DO terms. Each key must be a regular expression to search for terms and the associated
                value another regular expression that defines the final result
            do_terms_exclusion_list (List[str]): the list of DO ontology terms related to the DO annotations to be
                removed
        """
        self.load_gene_data_from_file()
        self.load_ontology_from_file(ontology_type=DataType.GO, ontology_url=self.go_ontology_url,
                                     ontology_cache_path=self.go_ontology_cache_path,
                                     terms_replacement_regex=go_terms_replacement_regex)
        self.load_associations_from_file(associations_type=DataType.GO, associations_url=self.go_associations_url,
                                         associations_cache_path=self.go_associations_cache_path,
                                         exclusion_list=go_terms_exclusion_list)
        self.load_ontology_from_file(ontology_type=DataType.DO, ontology_url=self.do_ontology_url,
                                     ontology_cache_path=self.do_ontology_cache_path,
                                     terms_replacement_regex=do_terms_replacement_regex)
        self.load_associations_from_file(associations_type=DataType.DO, associations_url=self.do_associations_url,
                                         associations_cache_path=self.do_associations_cache_path,
                                         exclusion_list=do_terms_exclusion_list)

