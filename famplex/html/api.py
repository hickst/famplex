# -*- coding: utf-8 -*-

"""Export FamPlex as a static site."""

import os
from collections import defaultdict

import click
import pandas as pd
import requests
from jinja2 import Environment, FileSystemLoader
from tqdm import tqdm

from famplex.load import load_descriptions, load_entities, load_equivalences, load_grounding_map, load_relations

HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
DOCS = os.path.join(ROOT, 'docs')
os.makedirs(DOCS, exist_ok=True)

environment = Environment(autoescape=True, loader=FileSystemLoader(HERE), trim_blocks=False)
index_template = environment.get_template('index.html')
term_template = environment.get_template('term.html')

try:
    from indra.ontology.bio import bio_ontology
except ImportError:
    from functools import lru_cache


    @lru_cache(maxsize=None)
    def get_name(namespace: str, identifier: str) -> str:
        """Get a name from identifier using the INDRA ontology web service."""
        url = 'http://34.230.33.149:8082/'
        res = requests.get(
            url + 'get_node_property',
            json={'ns': namespace, 'id': identifier, 'property': 'name', 'ontology': 'bio'},
        )
        return res.json()


    @lru_cache(maxsize=None)
    def get_identifier(namespace: str, name: str) -> str:
        """Get an identifier from name using the INDRA ontology web service."""
        url = 'http://34.230.33.149:8082/'
        res = requests.get(
            url + 'get_id_from_name',
            json={'ns': namespace, 'name': name, 'ontology': 'bio'},
        )
        return res.json()[1]
else:
    def get_name(namespace: str, identifier: str) -> str:
        name = bio_ontology.get_name(namespace, identifier)
        return name

    def get_identifier(namespace: str, name: str) -> str:
        _, identifier = bio_ontology.get_id_from_name(namespace, name)
        return identifier


@click.command()
@click.option('--directory', default=DOCS)
@click.option('--debug-links', is_flag=True)
def html(directory: str, debug_links: bool):
    """Export FamPlex as a static HTML site."""
    click.echo(f'outputting to {directory}')

    fplx_ids = load_entities()

    descriptions = {
        identifier: (source, text)
        for identifier, source, text in load_descriptions()
    }

    xrefs = defaultdict(set)
    for namespace, identifier, fplx_id in tqdm(load_equivalences(), desc='loading equivalences'):
        xrefs[fplx_id].add((namespace, identifier, get_name(namespace, identifier)))

    grounding_map = load_grounding_map()
    synonyms = defaultdict(set)
    for text, groundings in grounding_map.items():
        fplx_id = groundings.get('FPLX')
        if fplx_id:
            synonyms[fplx_id].add(text)

    incoming_relations = defaultdict(set)
    outgoing_relations = defaultdict(set)
    for ns1, id1, rel, ns2, id2 in tqdm(load_relations(), desc='loading relations'):
        if ns1 == 'FPLX':
            if ns2 == 'HGNC':
                id2, name2 = get_identifier(ns2, id2), id2
            else:
                name2 = get_name(ns2, id2)
            outgoing_relations[id1].add((rel, ns2, id2, name2))
        if ns2 == 'FPLX':
            if ns1 == 'HGNC':
                id1, name1 = get_identifier(ns1, id1), id1
            else:
                name1 = get_name(ns1, id1)
            incoming_relations[id2].add((ns1, id1, name1, rel))

    rows = [
        (
            fplx_id,
            *descriptions.get(fplx_id, (None, None)),  # splat operator * adds two columns at once
            len(xrefs.get(fplx_id, [])),
            len(synonyms.get(fplx_id, [])),
            len(incoming_relations.get(fplx_id, [])),
            len(outgoing_relations.get(fplx_id, [])),
        )
        for fplx_id in fplx_ids
    ]

    terms_df = pd.DataFrame(rows, columns=[
        'identifier', 'description_source', 'description_text', 'equivalences',
        'synonyms', 'in_edges', 'out_edges',
    ])
    index_html = index_template.render(
        terms_df=terms_df,
    )
    with open(os.path.join(directory, 'index.html'), 'w') as file:
        print(index_html, file=file)

    for _, row in tqdm(terms_df.iterrows(), total=len(terms_df.index), desc='writing terms'):
        subdirectory = os.path.join(directory, row.identifier)
        os.makedirs(subdirectory, exist_ok=True)
        term_html = term_template.render(
            row=row,
            synonyms=synonyms[row.identifier],
            xrefs=xrefs[row.identifier],
            incoming_relations=incoming_relations[row.identifier],
            outgoing_relations=outgoing_relations[row.identifier],
            debug_links=debug_links,
        )
        with open(os.path.join(subdirectory, 'index.html'), 'w') as file:
            print(term_html, file=file)


if __name__ == '__main__':
    html()
