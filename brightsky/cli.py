import datetime
import json
from multiprocessing import cpu_count

import click
from dateutil.tz import tzutc
from huey.consumer_options import ConsumerConfig

from brightsky import db, tasks, query
from brightsky.utils import parse_date


def dump_records(it):
    for record in it:
        print(json.dumps(record, default=str))


def migrate_callback(ctx, param, value):
    if value:
        db.migrate()


def parse_date_arg(ctx, param, value):
    if not value:
        return
    return parse_date(value)


@click.group()
@click.option(
    '--migrate', help='Migrate database before running command',
    is_flag=True, is_eager=True, expose_value=False, callback=migrate_callback)
def cli():
    pass


@cli.command(help='Apply all pending database migrations')
def migrate():
    db.migrate()


@cli.command(help='Parse a forecast or observations file')
@click.option('--path', help='Local file path to observations file')
@click.option('--url', help='URL of observations file')
@click.option(
    '--export/--no-export', default=False,
    help='Export parsed records to database')
def parse(path, url, export):
    if not path and not url:
        raise click.ClickException('Please provide either --path or --url')
    records = tasks.parse(path=path, url=url, export=export)
    if not export:
        dump_records(records)


@cli.command(help='Detect updated files on DWD Open Data Server')
@click.option(
    '--enqueue/--no-enqueue', default=False,
    help='Enqueue updated files for processing by the worker')
def poll(enqueue):
    files = tasks.poll(enqueue=enqueue)
    if not enqueue:
        dump_records(files)


@cli.command(help='Clean expired forecast and observations from database')
def clean():
    tasks.clean()


@cli.command(help='Start brightsky worker')
def work():
    from brightsky.worker import huey
    huey.flush()
    config = ConsumerConfig(worker_type='thread', workers=2*cpu_count()+1)
    config.validate()
    consumer = huey.create_consumer(**config.values)
    consumer.run()


@cli.command(help='Start brightsky API webserver')
@click.option('--bind', default='127.0.0.1:5000', help='Bind address')
@click.option(
    '--reload/--no-reload', default=False,
    help='Reload server on source code changes')
def serve(bind, reload):
    from brightsky.web import app, StandaloneApplication
    StandaloneApplication(
        app, bind=bind, workers=2*cpu_count()+1, reload=reload
    ).run()


@cli.command('query', help='Retrieve weather records')
@click.argument('lat', type=float)
@click.argument('lon', type=float)
@click.argument('date', required=False, callback=parse_date_arg)
@click.argument('last-date', required=False, callback=parse_date_arg)
@click.option(
    '--max-dist', type=int, default=50000,
    help='Maximum distance to observation location, in meters')
def query_weather(lat, lon, date, last_date, max_dist):
    if not date:
        date = datetime.datetime.now(tzutc()).replace(
            hour=0, minute=0, second=0, microsecond=0)
    records = query.weather(
        lat, lon, date, last_date=last_date, max_dist=max_dist)
    dump_records(dict(r) for r in records)
