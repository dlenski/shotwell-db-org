import datetime as dt
import sys
import os
import sqlite3 as db
import shutil
from argparse import ArgumentParser

# TODO: make event directory names configurable

DB_FILE = os.path.join(os.getenv('HOME'), '.local/share/shotwell/data/photo.db')
DATE_FORMAT = '%Y-%m-%d'

def create_argparser():
    parser = ArgumentParser(description='Reorganises shotwell\' photo directories')
    parser.add_argument('destination_dir', help='Where to put the new photo directories')
    parser.add_argument('--database', '-d', default=DB_FILE, dest='database_file',
                        help='Path to shotwell\'s database file')
    parser.add_argument('--date-format', default=DATE_FORMAT, dest='date_format',
                        help='Date format, look up strftime for details.')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--copy', '-c', action='store_const', const=shutil.copy2,
                       default=shutil.move, help='Copy images instead of moving',
                       dest='file_operator')
    group.add_argument('--no-clean', '-nc', action='store_const', const=False,
                       default=True, help='Do not remove empty photo directories',
                       dest='clean')

    return parser


def get_new_event_directory(conn, event_id, event_name):
    event_ts_sel = 'SELECT count(*) AS cnt, min(timestamp) AS min_ts, '\
                   'max(timestamp) AS max_ts FROM PhotoTable '\
                   'WHERE event_id=?'

    event_exp_sel = 'SELECT count(*) AS cnt, min(exposure_time) as min_et, '\
                    'max(exposure_time) as max_et FROM PhotoTable '\
                    'WHERE event_id=? AND exposure_time > 0'

    ev_cur = conn.cursor().execute(event_exp_sel, (event_id,))
    exp_cnt, min_et, max_et = ev_cur.fetchone()

    if exp_cnt > 0:
        min_date = dt.date.fromtimestamp(min_et)
        max_date = dt.date.fromtimestamp(max_et)
    else:
        # there are no photos in this event with exposure_time set, we'll
        # use the timestamp instead
        ts_cur = conn.cursor().execute(event_ts_sel, (event_id,))
        cnt, min_ts, max_ts = ts_cur.fetchone()

        if cnt == 0:
            # no photos in this event
            return None

        min_date = dt.date.fromtimestamp(min_ts)
        max_date = dt.date.fromtimestamp(max_ts)

    event_dir = min_date.stftime(date_format)
    if max_date != min_date:
        event_dir += ' - ' + max_date.strftime(date_format)
    if event_name:
        event_dir += ' - ' + event_name.replace('/', '-')

    return event_dir


def main():
    parser = create_argparser()
    args = parser.parse_args()

    db_file = args.database_file
    date_format = args.date_format
    dest_dir = args.destination_dir
    process_file = args.file_operator
    clean_dirs = args.clean

    if not (os.path.exists(db_file) and os.path.isfile(db_file)):
        sys.stderr.write("Database file %s does not exist.\n" % db_file)
        return 1

    if not (os.path.exists(dest_dir) and os.path.isdir(dest_dir)):
        sys.stderr.write("Invalid destination directory '%s'.\n" % dest_dir)
        return 2

    conn = db.connect(db_file, isolation_level=None)
    conn.row_factory = db.Row

    event_sel = 'SELECT id, name FROM EventTable'

    photo_sel = 'SELECT id, filename FROM PhotoTable WHERE event_id=? '\
                'UNION ALL '\
                'SELECT id, filename FROM VideoTable WHERE event_id=?'

    photo_upd = 'UPDATE PhotoTable SET filename=? WHERE id=?'

    events = conn.cursor().execute(event_sel).fetchall()
    for event in events:
        print 'Processing event', event['id'], ',', event['name']

        event_dir = get_new_event_directory(conn, event['id'], event['name'])

        if event_dir is None:
            continue

        new_dir = os.path.join(dest_dir, event_dir)
        if not os.path.exists(new_dir):
            os.mkdir(new_dir)

        photo_cur = conn.cursor().execute(photo_sel, (event['id'], event['id']))
        photos = photo_cur.fetchall()

        for photo in photos:
            # create new file name
            old_dir, filename = os.path.split(photo['filename'])

            if old_dir == new_dir:
                # photo is already in the correct place
                continue

            new_path = os.path.join(new_dir, filename)

            # if there's already a photo with the same filename
            dupl = 1
            while os.path.exists(new_path):
                name, ext = os.path.splitext(filename)
                name += '_%d' % dupl
                dupl += 1
                new_path = os.path.join(new_dir, name + ext)

            upd = conn.cursor()
            upd.execute(photo_update, (new_path, photo['id']))
            process_file(old_path, new_path)

            if clean_dirs:
                # delete directory if empty
                while os.listdir(old_dir) == []:
                    os.rmdir(old_dir)
                    old_dir = os.path.dirname(old_dir)

    return 0


if __name__ == '__main__':
    sys.exit(main())
