import io
import os
import re
import sys
import csv
import urllib
import itertools
from collections import defaultdict
from indra.databases import hgnc_client

hgnc_fam_url = ('http://ftp.ebi.ac.uk/pub/databases/genenames/new/csv/'
                'genefamily_db_tables/')
gene_fam_file = 'gene_has_family.csv'
family_file = 'family.csv'
hier_closure_file = 'hierarchy_closure.csv'
hier_file = 'hierarchy.csv'


def read_csv_from_ftp(fname):
    """Return a generator for a CSV file opened from HGNC's FTP server."""
    url = hgnc_fam_url + fname
    print('Loading %s' % url)
    req = urllib.request.Request(url)
    res = urllib.request.urlopen(req)
    reader = csv.reader(io.TextIOWrapper(res))
    for row in reader:
        yield row


def _read_hgnc_family_genes():
    """Return dicts representing gene/familiy relationships in HGNC."""
    family_to_gene = defaultdict(list)
    gene_to_family = defaultdict(list)
    for gene_id, family_id in read_csv_from_ftp(gene_fam_file):
        family_to_gene[family_id].append(gene_id)
        gene_to_family[gene_id].append(family_id)
    return gene_to_family, family_to_gene


def _read_family_info():
    """Return dict representing HGNC family information"""
    families = {}
    for idx, row in enumerate(read_csv_from_ftp(family_file)):
        if idx == 0:
            header = row
            continue
        families[row[0]] = {k: v for k, v in zip(header, row)}
    return families


def _read_hierarchy_info():
    """Return dict representing HGNC family membership information."""
    children = defaultdict(list)
    for idx, (parent, child) in enumerate(read_csv_from_ftp(hier_file)):
        if idx == 0:
            continue
        children[parent].append(child)
    return children


# Read HGNC resource files
families = _read_family_info()
children = _read_hierarchy_info()
gene_to_family, family_to_gene = _read_hgnc_family_genes()


def get_famplex_id(family):
    """Generate an appropriate FPLX ID for an HGNC family"""
    if family['abbreviation']:
        return family['abbreviation'].strip().replace(', ', '_')
    else:
        replaces = {' ': '_', '-': '_', ',': ''}
        name = family['name'].strip()
        for k, v in replaces.items():
            name = name.replace(k, v)
        return name


def is_pseudogene(gene):
    return re.match(r'^.*\d+P$', gene) is not None


def get_relations_from_root(root_id, relations=None):
    """Return a set of relations starting from a given root."""
    if relations is None:
        relations = []
    family_info = families[root_id]
    child_ids = children.get(root_id)
    famplex_id = get_famplex_id(family_info)
    # In this case this HGNC family has genes as its children
    gene_members = family_to_gene[root_id]
    for gene in gene_members:
        gene_name = hgnc_client.get_hgnc_name(gene)
        if is_pseudogene(gene_name):
            print('Assuming %s is a pseudogene, skipping' % gene_name)
            continue
        rel = ('HGNC', gene_name, 'isa', 'FPLX', famplex_id, root_id)
        relations.append(rel)
    # In this case this HGNC family is an intermediate that has further
    # families as its children
    if child_ids is not None:
        for child_id in child_ids:
            # We want to skip families that only consist of a single gene,
            # and therefore these genes are directly linked to their
            # "grandparent" without recursively adding the intermediate
            # family parent.
            grandchild_ids = children.get(child_id)
            child_gene_members = family_to_gene[child_id]
            if not grandchild_ids and len(child_gene_members) == 1:
                gene_name = hgnc_client.get_hgnc_name(child_gene_members[0])
                if is_pseudogene(gene_name):
                    print('Assuming %s is a pseudogene, skipping' % gene_name)
                    continue
                print('HGNC family %s has one gene member %s which will be '
                      'linked directly to %s' % (child_id, gene_name,
                                                 famplex_id))
                rel = ('HGNC', gene_name, 'isa', 'FPLX', famplex_id, root_id)
                relations.append(rel)
            # In this case, the child contains either further families or
            # multiple genes, and we recursively add its relations
            else:
                child_info = families[child_id]
                child_famplex_id = get_famplex_id(child_info)
                rel = ('FPLX', child_famplex_id, 'isa', 'FPLX', famplex_id,
                       root_id)
                relations.append(rel)
                get_relations_from_root(child_id, relations)
    return relations


def add_relations_to_famplex(relations):
    """Append a list of relations to relations.csv"""
    rel_file = os.path.join(os.path.dirname(__file__), os.pardir,
                            'relations.csv')
    with open(rel_file, 'a') as fh:
        for rel in relations:
            fh.write(','.join(rel[:-1]) + '\r\n')


def add_entities_to_famplex(entities):
    """Append a list of entities to entities.csv"""
    ents_file = os.path.join(os.path.dirname(__file__), os.pardir,
                             'entities.csv')
    with open(ents_file, 'a') as fh:
        for ent in entities:
            fh.write('%s\r\n' % ent)


def add_equivalences(relations):
    """Based on a list of relations, append equivalences to equivalences.csv"""
    hgnc_fam_ids = sorted(list(set(int(r[5]) for r in relations)))
    equivs = []
    for fid in hgnc_fam_ids:
        equivs.append(('HGNC_GROUP', str(fid),
                       get_famplex_id(families[str(fid)])))
    equivs_file = os.path.join(os.path.dirname(__file__), os.pardir,
                               'equivalences.csv')
    with open(equivs_file, 'a') as fh:
        for eq in equivs:
            fh.write('%s\r\n' % ','.join(eq))


def find_overlaps(relations):
    """Try to detect overlaps between existing FamPlex and HGNC families."""
    all_gene_names = {r[1]: r[4] for r in relations if r[0] == 'HGNC'}

    rel_file = os.path.join(os.path.dirname(__file__), os.pardir,
                            'relations.csv')
    covered_genes = set()
    covered_families = set()
    fam_members = defaultdict(list)
    hgnc_families = set()
    with open(rel_file, 'r') as fh:
        for sns, sid, rel, tns, tid in csv.reader(fh):
            if sns == 'HGNC' and tns == 'FPLX':
                fam_members[tid].append(sid)
            if sns == 'HGNC' and sid in all_gene_names:
                covered_genes.add(sid)
                print('%s covered already' % sid)
                covered_families.add(tid)
                hgnc_families.add(all_gene_names[sid])

    fplx_fam_members = {}
    for famplex_fam in covered_families:
        fplx_fam_members[famplex_fam] = set(fam_members[famplex_fam])

    fplx_fam_members = sorted(fplx_fam_members.items(),
                              key=lambda x: list(x[1])[0])

    hgnc_fam_members = {}
    for hgnc_fam in hgnc_families:
        hgnc_fam_members[hgnc_fam] = set(g for g, f in all_gene_names.items()
                                         if f == hgnc_fam)
    hgnc_fam_members = sorted(hgnc_fam_members.items(),
                              key=lambda x: list(x[1])[0])

    totally_redundant = set()
    for ff, hf in zip(fplx_fam_members, hgnc_fam_members):
        if set(ff[1]) == set(hf[1]):
            totally_redundant.add(hf[0])
            print('FamPlex %s and HGNC-derived %s are exactly the same.' %
                  (ff[0], hf[0]))
        else:
            print('FamPlex %s and HGNC-derived %s are overlapping.' %
                  (ff[0], hf[0]))
        print('Members of %s are: %s' % (ff[0], ','.join(sorted(ff[1]))))
        print('Members of %s are: %s' % (hf[0], ','.join(sorted(hf[1]))))
    return totally_redundant


if __name__ == '__main__':
    # Start from one or more root family IDs to process from
    hgnc_group_ids = sys.argv[1:]
    relations = []
    for hgnc_group_id in hgnc_group_ids:
        print('Loading relations for HGNC group: %s' % hgnc_group_id)
        relations += get_relations_from_root(hgnc_group_id)
    # Sort the relations
    relations = sorted(list(set(relations)), key=lambda x: (x[4], x[1]))
    # Find and eliminate families that are exactly the same as existing ones
    totally_redundant = find_overlaps(relations)
    relations = [r for r in relations if r[4] not in totally_redundant]
    # Get a flat list of entities
    entities = sorted(list(set(r[4] for r in relations)))
    # Extend FamPlex resource files with new information
    add_relations_to_famplex(relations)
    add_entities_to_famplex(entities)
    add_equivalences(relations)
