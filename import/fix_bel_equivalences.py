import csv
import pathlib

import pyobo

from famplex.load import _load_csv

HERE = pathlib.Path(__file__).parent.resolve()


def _write_csv(filename, rows):
    """Load famplex csv file as list of rows."""
    with open(filename, 'w') as f:
        writer = csv.writer(f, delimiter=str(u','),
                            lineterminator='\r\n',
                            quoting=csv.QUOTE_MINIMAL,
                            quotechar=str(u'"'))
        writer.writerows(rows)


def main():
    path = HERE.parent.joinpath('equivalences.csv')
    rows = list(_load_csv(path))

    new_rows = []
    scomp_name_id = pyobo.get_name_id_mapping('scomp')
    sfam_name_id = pyobo.get_name_id_mapping('sfam')
    for xref_ns, xref_id, fplx_id in rows:
        if xref_ns == 'BEL':
            scomp_id = scomp_name_id.get(xref_id)
            if scomp_id is not None:
                new_rows.append(('SCOMP', scomp_id, fplx_id))
                continue
            sfam_id = sfam_name_id.get(xref_id)
            if sfam_id is not None:
                new_rows.append(('SFAM', sfam_id, fplx_id))
                continue
            print('could not look up BEL', xref_id)
    rows.extend(new_rows)
    _write_csv(path, rows)


if __name__ == '__main__':
    main()
