#!/usr/bin/python3
# -*- coding: utf-8 -*-

import datetime
import itertools
import json
import os
import os.path
import re
import sqlite3
import textwrap
import traceback
import unicodedata
import base64
from email.message import EmailMessage

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from flask import Flask, flash, g, redirect, render_template, request, Response, url_for
from flask_mail import Mail, Message

from auth import User, handle_login, handle_logout, login_required
from urllib.parse import unquote

import config

def default_config():
    return dict(
        SECRET_KEY=os.urandom(128),
        DEBUG=True
    )


app = Flask(__name__)
app.config.update(default_config())
app.config.from_pyfile('config.py')
app.config['USERS'] = { x[0]: User(*x) for x in app.config['USERS'] }


def connect_db():
    db = sqlite3.connect(app.config['DB_PATH'])
#    db = sqlite3.connect(
#        'file:/%s?mode=ro'.format(app.config['DB_PATH']), uri=True
#    )
    db.row_factory = sqlite3.Row
    db.cursor().execute('PRAGMA foreign_keys=ON')
    return db


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect_db()
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def do_query(cursor, query, *params):
    cursor.execute(query, params)
    return [tuple(r) for r in cursor.fetchall()]


@app.errorhandler(Exception)
def handle_exception(ex):
  ex_text = traceback.format_exc()
  return render_template('exception.html', ex=ex_text), 500


@app.route('/login', methods=['GET', 'POST'])
def login():
  return handle_login(lambda x: None, 'front')


@app.route('/logout')
@login_required
def logout():
  return handle_logout(lambda x: None)


@app.route('/')
def front():
    last_updated = datetime.date.fromtimestamp(os.path.getmtime(app.config['DB_PATH']))
    return render_template(
        'front.html',
        last_updated=last_updated
    )


@app.route('/privacy')
def privacy():
    return render_template(
        'privacy.html'
    )

# FIXME: always display with most recent name
# FIXME: clean up queries

@app.route('/persona/<name>', methods=['GET'])
def persona(name):
    c = get_db().cursor()
    import urllib.parse
    uname = urllib.parse.unquote(name)
    query_rst = do_query(c, 'SELECT people.id, people.surname IS NOT NULL OR people.forename IS NOT NULL, regions.name, people.blazon, people.emblazon FROM personae JOIN people ON personae.person_id = people.id JOIN regions ON people.region_id = regions.id WHERE personae.name = ?', uname)[0]

    person_id, has_modname, region, blazon, emblazon = query_rst 

    official_id, official_name = do_query(c, 'SELECT id, name FROM personae WHERE person_id = ? AND official = 1', person_id)[0];

    other = do_query(c, 'SELECT name FROM personae WHERE person_id = ? AND id != ? ORDER BY name', person_id, official_id);
    if other:
        other = [f[0] for f in other]

    if emblazon:
        emblazon = '<img class="emblazon" src="{}"/>'.format(url_for('static', filename='images/arms/' + emblazon))
    else:
        emblazon = '<div class="emblazon noarms"><div>I have not given<br/>Post Horn my<br/> registered<br/> arms.</div></div>'

    awards = do_query(c, 'SELECT DISTINCT p2.name, award_types.name, awards.date, crowns.name, events.name FROM personae AS p1 JOIN personae AS p2 ON p1.person_id = p2.person_id JOIN awards ON p2.id = awards.persona_id JOIN award_types ON awards.type_id = award_types.id JOIN events ON awards.event_id = events.id LEFT OUTER JOIN crowns ON awards.crown_id = crowns.id WHERE p1.name = ? ORDER BY awards.date, award_types.name', uname)

    return render_template(
        'persona.html',
        name=official_name,
        other=other,
        region=region,
        has_modname=has_modname,
        blazon=blazon,
        emblazon=emblazon,
        awards=awards,
        persona_id=official_id
    )


# FIXME: fails with just one name component

@app.route('/person/<surname>/<forename>', methods=['GET'])
def person(surname, forename):
    c = get_db().cursor()

    awards = do_query(c, 'SELECT award_types.name, awards.date, crowns.name, events.name FROM awards JOIN personae ON awards.persona_id = personae.id JOIN people ON personae.person_id = people.id JOIN award_types ON awards.type_id = award_types.id JOIN events ON awards.event_id = events.id LEFT OUTER JOIN crowns ON awards.crown_id = crowns.id WHERE people.surname = ? AND people.forename = ? ORDER BY awards.date, award_types.name', unquote(surname), unquote(forename))

    return render_template(
        'person.html',
        surname=unquote(surname),
        forename=unquote(forename),
        awards=awards
    )


# TODO: add checkbox for name when given vs name last used?

@app.route('/awards', methods=['GET', 'POST'])
def awards():
    results = None

    c = get_db().cursor()
    awards_sca = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 1 ORDER BY award_types.name')
    awards_dw = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 2 ORDER BY award_types.name')
    awards_id = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 27 ORDER BY award_types.name')
    awards_nm = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 3 ORDER BY award_types.name')
    awards_aa = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 4 ORDER BY award_types.name')
    awards_kc = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 5 ORDER BY award_types.name')
    awards_st = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 25 ORDER BY award_types.name')
    awards_gv = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 30 ORDER BY award_types.name')
    awards_ep = do_query(c, 'SELECT award_types.id, award_types.name FROM award_types WHERE award_types.group_id = 42 ORDER BY award_types.name')

    if request.method == 'POST':
        a_ids = [int(v) for v in request.form if v.isdigit()]
        results = do_query(c, 'SELECT personae.name, award_types.name, awards.date, crowns.name, events.name FROM awards JOIN personae ON awards.persona_id = personae.id JOIN award_types ON awards.type_id = award_types.id JOIN events ON awards.event_id = events.id LEFT OUTER JOIN crowns ON awards.crown_id = crowns.id WHERE award_types.id IN ({}) ORDER BY awards.date, personae.name, award_types.name'.format(','.join(['?'] * len(a_ids))), *a_ids)

    return render_template(
        'awards.html',
        awards_sca=awards_sca,
        awards_dw=awards_dw,
        awards_id=awards_id,
        awards_nm=awards_nm,
        awards_aa=awards_aa,
        awards_kc=awards_kc,
        awards_st=awards_st,
        awards_gv=awards_gv,
        awards_ep=awards_ep,
        results=results
    )


@app.route('/date', methods=['GET'])
def date():
    begin = request.args['begin'].strip()
    end = request.args['end'].strip()
    results = None

    c = get_db().cursor()
    results = do_query(c, 'SELECT personae.name, award_types.name, awards.date, crowns.name, events.name FROM personae JOIN awards ON personae.id = awards.persona_id JOIN award_types ON awards.type_id = award_types.id JOIN events ON awards.event_id = events.id LEFT OUTER JOIN crowns ON awards.crown_id = crowns.id WHERE date(?) <= date(awards.date) AND date(awards.date) <= date(?) ORDER BY awards.date, personae.name, award_types.name', begin, end)

    return render_template(
        'date.html',
        begin=begin,
        end=end,
        results=results
    )


@app.route('/award', methods=['GET'])
def award():
    award = request.args['award'].strip()
    results = None

    c = get_db().cursor()
    results = do_query(c, 'SELECT personae.name, award_types.name, awards.date, crowns.name, events.name FROM personae JOIN awards ON personae.id = awards.persona_id JOIN award_types ON awards.type_id = award_types.id JOIN events ON awards.event_id = events.id LEFT OUTER JOIN crowns ON awards.crown_id = crowns.id WHERE award_types.name LIKE ? ORDER BY awards.date, personae.name, award_types.name', '%{}%'.format(award))

    return render_template(
        'award.html',
        award=award,
        results=results
    )


@app.route('/crown', methods=['GET'])
def crown():
    crown_id = request.args['crown_id']
    results = None

    c = get_db().cursor()

    crown = do_query(c, 'SELECT name FROM crowns WHERE id = ?', crown_id)[0][0]

    results = do_query(c, 'SELECT personae.name, award_types.name, awards.date, crowns.name, events.name FROM personae JOIN awards ON personae.id = awards.persona_id JOIN award_types ON awards.type_id = award_types.id JOIN events ON awards.event_id = events.id JOIN crowns ON awards.crown_id = crowns.id WHERE crowns.id = ? ORDER BY awards.date, personae.name, award_types.name', crown_id)

    return render_template(
        'crown.html',
        crown=crown,
        results=results
    )


# FIXME: simplify query?

@app.route('/op', methods=['GET', 'POST'])
def op():
    headers = None
    results = None

    if request.method == 'POST':
        min_precedence = int(request.form['precedence'].strip())
        c = get_db().cursor()
        results = do_query(c, 'SELECT DISTINCT cur.name, awards.date, award_types.precedence FROM awards JOIN personae ON awards.persona_id = personae.id JOIN award_types ON awards.type_id = award_types.id LEFT JOIN (SELECT personae.person_id, award_types.precedence FROM awards JOIN personae ON awards.persona_id = personae.id JOIN award_types ON awards.type_id = award_types.id) AS pjoin ON personae.person_id = pjoin.person_id AND award_types.precedence < pjoin.precedence LEFT JOIN (SELECT personae.person_id, awards.date, award_types.precedence FROM awards JOIN personae ON awards.persona_id = personae.id JOIN award_types ON awards.type_id = award_types.id) AS djoin ON personae.person_id = djoin.person_id AND award_types.precedence = djoin.precedence AND awards.date > djoin.date JOIN personae AS cur ON personae.person_id = cur.person_id WHERE pjoin.precedence IS NULL AND djoin.date IS NULL AND award_types.precedence >= ? AND cur.official = 1 ORDER BY award_types.precedence DESC, awards.date, cur.name', min_precedence)

        headers = {
            1000: 'Duchy',
             900: 'County',
             800: 'Viscounty',
             700: 'Bestowed peerages',
             600: 'Court Barony',
             500: 'Grant of Arms awards',
             400: 'Grant of Arms',
             300: 'Award of Arms awards',
             200: 'Award of Arms',
             100: 'All awards'
        }

        results = itertools.groupby(results, key=lambda r: r[2])

    return render_template(
        'op.html',
        headers=headers,
        results=results
    )


@app.route('/reigns', methods=['GET'])
def reigns():
    c = get_db().cursor()
    principality = do_query(c, 'SELECT sov1 || " and " || sov2, begin, end FROM reigns WHERE date(begin) < date("1993-06-05") ORDER BY begin')
    kingdom = do_query(c, 'SELECT sov1 || " and " || sov2, begin, end FROM reigns WHERE date(begin) >= date("1993-06-05") ORDER BY begin')

    return render_template(
        'reigns.html',
        principality=principality,
        kingdom=kingdom
    )


# TODO: make an alphabetic index

@app.route('/armorial', methods=['GET'])
def armorial():
    c = get_db().cursor()
    results = do_query(c, 'SELECT personae.name, people.emblazon FROM people JOIN personae ON personae.person_id = people.id WHERE people.emblazon IS NOT NULL AND personae.official = 1 ORDER BY personae.name')

    return render_template(
        'armorial.html',
        columns=6,
        results=results
    )


@app.route('/signet/backlog', methods=['GET', 'POST'])
@login_required
def backlog():
    c = get_db().cursor()
    results = do_query(c, 'SELECT personae.name, award_types.name, crowns.name, awards.date, events.name, scroll_status.name, scribes.name FROM awards JOIN personae ON awards.persona_id = personae.id JOIN award_types ON awards.type_id = award_types.id JOIN events ON awards.event_id = events.id LEFT OUTER JOIN crowns ON awards.crown_id = crowns.id JOIN scroll_status ON awards.scroll_status_id = scroll_status.id JOIN scribes ON awards.scribe_id = scribes.id WHERE awards.scroll_status_id != 4 ORDER BY awards.date, personae.name')

    return render_template(
        'backlog.html',
        results=results
    )


class FormError(Exception):
  def __init__(self, message):
    super(FormError, self).__init__()
    self.message = message


def search_modern(c, surname, forename):
    query = 'SELECT id, surname, forename FROM people WHERE '

    if surname:
        if forename:
            query += 'surname LIKE ? AND forename LIKE ?'
            params = ('%{}%'.format(surname), '%{}%'.format(forename))
        else:
            query += 'surname LIKE ?'
            params = ('%{}%'.format(surname),)
    else:
        query += 'forename LIKE ?'
        params = ('%{}%'.format(forename),)

    query += ' ORDER BY surname, forename'

    matches = do_query(c, query, *params)

    if len(matches) == 1:
        return redirect(url_for(
            'person',
            surname=matches[0][1],
            forename=matches[0][2]
        ))
    else:
        return render_template('choose_person.html', matches=matches)


SEARCH_TRANS = str.maketrans({
    'Æ': 'Ae',
    'æ': 'ae',
    'Œ': 'Oe',
    'œ': 'oe',
    'đ': 'd',
    'ø': 'o',
    'Ø': 'O',
    'þ': 'th',
    'Þ': 'Th',
    'ð': 'dh',
    'ß': 'ss'
})


def normalize(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).translate(SEARCH_TRANS)


def match_persona(c, name):
    sname = normalize(name)

    #rows = do_query(c, 'SELECT p2.id, p2.name, p1.person_id, p2.official FROM personae AS p1 JOIN personae AS p2 ON p1.person_id = p2.person_id  WHERE p1.search_name LIKE ? AND p1.official = 1 ORDER BY p1.person_id, p2.official DESC, p2.name', '%{}%'.format(sname))
    rows = do_query(c,'SELECT p2.id, p2.name, p1.person_id, p2.official FROM personae AS p1 JOIN personae AS p2 ON p1.person_id = p2.person_id  WHERE p1.search_name LIKE ?  ORDER BY p1.person_id, p2.official DESC, p2.name', '%{}%'.format(sname))

    results = [[i[1] for i in gi] for _, gi in itertools.groupby(rows, lambda r: r[2])]
    # sort name groups by their header name
    results.sort(key=lambda x: (x[0].casefold(), x[0]))

    return results


def search_persona(c, persona):
    matches = match_persona(c, persona)

    if len(matches) == 1:
        return redirect(url_for('persona', name=matches[0][0]))
    else:
        return render_template('choose_persona.html', matches=matches)


def throw_if(*args):
    if any(args):
        raise FormError('Choose a single type of search.')


def get_crowns_list(c):
    return do_query(c, 'SELECT id, name FROM crowns ORDER BY name')


def stripped(d, k):
    return d.get(k, default='').strip() or None


@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        persona = stripped(request.form, 'persona')
        forename = stripped(request.form, 'forename')
        surname = stripped(request.form, 'surname')
        begin = stripped(request.form, 'begin')
        end = stripped(request.form, 'end')
        crown = stripped(request.form, 'crown')
        award = stripped(request.form, 'award')

        try:
            if forename or surname:
                throw_if(persona, begin, end, crown, award)
                return search_modern(get_db().cursor(), surname, forename)
            elif persona:
                throw_if(forename, surname, begin, end, crown, award)
                return search_persona(get_db().cursor(), persona)
            elif begin or end:
                throw_if(forename, surname, persona, crown, award)
                return redirect(url_for('date', begin=begin, end=end))
            elif crown:
                throw_if(forename, surname, persona, begin, end, award)
                return redirect(url_for('crown', crown_id=crown))
            elif award:
                throw_if(forename, surname, persona, begin, end, crown)
                return redirect(url_for('award', award=award))
        except Exception as e:
            flash(e.message, 'error')

    crowns = get_crowns_list(get_db().cursor())
    return render_template(
        'search.html',
        crowns=crowns
    )


@app.template_filter('paragraphize')
def paragraphize(text):
    text = '\n'.join(l.strip() for l in text.splitlines())
    paras = re.split(r'\n{2,}', text)
    return '\n\n'.join('<p>{}</p>'.format(p) for p in paras)


REC_CSV_TRANS = str.maketrans({
    '\n': ' ',
    '\r': ' ',
    '"':  None,
    '\'': None
})


@app.route('/recommend', methods=['GET', 'POST'])
def recommend():

    data = {}
    state = 0

    if request.method == 'POST':
        state = request.form.get('state', default=0, type=int)

        if state == 0:
            persona_search = normalize(stripped(request.form, 'persona_search'))

            c = get_db().cursor()

            rows = do_query(c, 'SELECT p2.id, p2.name, p1.person_id, p2.official FROM personae AS p1 JOIN personae AS p2 ON p1.person_id = p2.person_id  WHERE p1.search_name LIKE ? AND p1.official = 1 ORDER BY p1.person_id, p2.official DESC, p2.name', '%{}%'.format(persona_search))

            results = [[(i[0], i[1]) for i in gi] for _, gi in itertools.groupby(rows, lambda r: r[2])]
            results.sort(key=lambda x: (x[0][1].casefold(), x[0][1]))

            data['matches'] = results
            state = 1

        elif state == 1:
            c = get_db().cursor()

            data['persona_id'] = persona_id = request.form.get('persona', type=int)
            if persona_id is None:
                data['persona'] = stripped(request.form, 'unknown')
                data['awards'] = []
            else:
                data['persona'] = do_query(c, 'SELECT name FROM personae WHERE id =  ?', persona_id)[0][0]
                data['awards'] = do_query(c, 'SELECT award_types.name, awards.date, award_types.precedence FROM personae AS p1 JOIN personae AS p2 ON p1.person_id = p2.person_id JOIN awards ON p2.id = awards.persona_id JOIN award_types ON awards.type_id = award_types.id WHERE p1.id = ? ORDER BY awards.date, award_types.name', persona_id)

            data['in_op'] = persona_id is not None

            data['unawards'] = do_query(c, 'SELECT award_types.id, award_types.name, CASE award_types.group_id WHEN 1 THEN 2 ELSE award_types.group_id END AS group_id, award_types.precedence FROM award_types LEFT JOIN (SELECT award_types.id FROM personae AS p1 JOIN personae AS p2 ON p1.person_id = p2.person_id JOIN awards ON p2.id = awards.persona_id JOIN award_types ON awards.type_id = award_types.id WHERE p1.id = ?) AS a ON award_types.id = a.id WHERE award_types.group_id IN (1, 2, 3, 4, 5, 25, 27, 30, 42) AND (award_types.open = 1 OR award_types.open IS NULL) AND award_types.id NOT IN (16, 27, 28, 29, 30, 49) AND a.id IS NULL ORDER BY group_id, award_types.precedence, award_types.name' , persona_id)

            data['unawards'] = { g: list(gi) for g, gi in
                itertools.groupby(data['unawards'], lambda x: x[2])
            }

            if 2 in data['unawards']:
                # omit AoA if they have any AoA-level awards
                # omit GoA if they have any GoA-level awards
                has_aoa = any(a[2] == 300 for a in data['awards'])
                has_goa = any(a[2] == 500 for a in data['awards'])
                data['unawards'][2] = [u for u in data['unawards'][2] if (not has_aoa or u[0] != 1) and (not has_goa or u[0] != 11)]

#            data['sendto'] = [r[0] for r in do_query(c, 'SELECT name FROM groups WHERE id IN (2, 3, 4, 5, 25, 27, 30)')]
            data['sendto'] = {
                2: 'Drachenwald',
                27: 'Insulae Draconis',
                3: 'Nordmark',
                4: 'Aarnimetsä',
                30: 'Gotvik',
                5: 'Knight\'s Crossing',
                25: 'Styringheim',
                42: 'Eplaheimr'
            }
            state = 2

        elif state == 2:

            your_forename = stripped(request.form, 'your_forename')
            your_surname = stripped(request.form, 'your_surname')
            your_persona = stripped(request.form, 'your_persona')
            your_email = stripped(request.form, 'your_email')

            persona = stripped(request.form, 'persona')
            persona_id = request.form.get('persona_id', type=int)

            time_served = stripped(request.form, 'time_served')
            gender = stripped(request.form, 'gender')
            branch = stripped(request.form, 'branch')

            awards = request.form.getlist('awards[]', type=int)
            crowns = request.form.getlist('crowns[]', type=int)
            recommendation = stripped(request.form, 'recommendation')

            events = stripped(request.form, 'events')

            scribe = stripped(request.form, 'scribe')
            scribe_email = stripped(request.form, 'scribe_email')

            c = get_db().cursor()
            crown_names = [n[0] for n in do_query(c, 'SELECT name FROM groups WHERE id IN ({})'.format(','.join(['?'] * len(crowns))), *crowns)]
            award_names = [n[0] for n in do_query(c, 'SELECT name FROM award_types WHERE id IN ({})'.format(','.join(['?'] * len(awards))), *awards)]

            data = {
                'your_forename': your_forename,
                'your_surname': your_surname,
                'your_persona': your_persona,
                'your_email': your_email,
                'persona': persona,
                'persona_id': persona_id,
                'time_served': time_served,
                'gender': gender,
                'branch': branch,
                'awards': awards,
                'award_names': award_names,
                'crowns': crowns,
                'crown_names': crown_names,
                'recommendation': recommendation,
                'events': events,
                'scribe': scribe,
                'scribe_email': scribe_email
            }

            state = 3

        elif state == 3:
            your_email = stripped(request.form, 'your_email')

            rec = stripped(request.form, 'recommendation')
            rec_sanitized = rec.translate(REC_CSV_TRANS)

            body_vars = {
                'your_forename': stripped(request.form, 'your_forename'),
                'your_surname': stripped(request.form, 'your_surname'),
                'your_persona': stripped(request.form, 'your_persona'),
                'your_email': your_email,
                'persona': stripped(request.form, 'persona'),
                'time_served': stripped(request.form, 'time_served'),
                'gender': stripped(request.form, 'gender'),
                'branch': stripped(request.form, 'branch'),
                'award_names': ', '.join(request.form.getlist('award_names[]')),
                'recommendation': rec,
                'recommendation_sanitized': rec_sanitized,
                'events': stripped(request.form, 'events'),
                'scribe': stripped(request.form, 'scribe') or '',
                'scribe_email': stripped(request.form, 'scribe_email') or '',
                'date': datetime.date.today()
            }

            body_fmt = '''
{your_forename} {your_surname}
{your_persona}
{your_email}

Recommendation of {persona}
'''

            if body_vars['time_served']:
                body_fmt += '\nTime in the Society: {time_served}'

            if body_vars['gender']:
                body_fmt += '\nGender: {gender}'

            if body_vars['branch']:
                body_fmt += '\nBranch: {branch}'

            body_fmt += '''
For the following awards: {award_names}

{recommendation}
'''
            if body_vars['events']:
                body_fmt += '\nEvents: {events}'

            if body_vars['scribe'] or body_vars['scribe_email']:
                body_fmt += '\nSuggested scribe: {scribe} {scribe_email}'

            body_fmt += '''

========== Pasteable summary ==========
Date | Recommender's Real Name | Recommender's SCA Name | Recommender's Email Address | SCA Name | Time in the SCA | Gender | Local Group | Awards | Events Person Will Attend | Suggested Scribe Name | Suggested Scribe Email Address | Reason for Recommendation
{date}|{your_forename} {your_surname}|{your_persona}|{your_email}|{persona}|{time_served}|{gender}|{branch}|{award_names}|{events}|{scribe}|{scribe_email}|{recommendation_sanitized}
'''

            body = body_fmt.format(**body_vars)

            body = '\n'.join(itertools.chain.from_iterable(textwrap.wrap(para, width=72) or [''] for para in body.split('\n'))).strip()

            crowns = request.form.getlist('crowns[]', type=int)

            crown_emails = {
                 2: [
                        'king@drachenwald.sca.org',
                        'queen@drachenwald.sca.org',
                        'crownprince@drachenwald.sca.org',
                        'crownprincess@drachenwald.sca.org'
                    ],
                27: ['prince@insulaedraconis.org', 'princess@insulaedraconis.org'],
                 3: ['furste@nordmark.org', 'furstinna@nordmark.org'],
                 4: ['paroni@aarnimetsa.org', 'paronitar@aarnimetsa.org'],
                30: ['baron@gotvik.se', 'baroness@gotvik.se'],
                 5: ['baron@knightscrossing.org', 'baronin@knightscrossing.org'],
                25: ['baron@styringheim.se', 'baronessa@styringheim.se'],
                42: ['baron.eplaheimr@gmail.com', 'baroness.eplaheimr@gmail.com']
            }

            to = [a for c in crowns for a in crown_emails[c]]

            msg = Message(
                'Recommendation',
                sender='noreply@op.drachenwald.sca.org',
                recipients=to,
                cc=[your_email],
                body=body
            )

            #mail.send(msg)
            try:
                scopes = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.compose']
                cred_info = {"type": "service_account",
                             "project_id": "dw-order-of-precedence",
                             "private_key_id": GOOGLE_KEY_ID,
                             "private_key": GOOGLE_KEY_SECRET,
                             "client_email": "artificial-deputy-for-the-orde@dw-order-of-precedence.iam.gserviceaccount.com",
                             "client_id": "111021806773359996540",
                             "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                             "token_uri": "https://oauth2.googleapis.com/token",
                             "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                             "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/artificial-deputy-for-the-orde%40dw-order-of-precedence.iam.gserviceaccount.com"
                }
            
                
                credentials = service_account.Credentials.from_service_account_info(info=cred_info, scopes=scopes)
            
                service = build('gmail', 'v1', credentials=credentials.with_subject('recommendations@drachenwald.sca.org'))
                message = EmailMessage()
            
                message.set_content(body)
                message['To'] = to
                message['Cc'] = [your_email]
                message['From']= cred_info["client_email"]
                message['Subject'] = 'Recommendation'
            
                encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
                create_message = {
                            'raw': encoded_message
                    }
                # pylint: disable=E1101
                
                send_message = (service.users().messages().send
                                (userId="me", body=create_message).execute())
            except HttpError as error:
                print('An error occurred: {error} please let the webminister know by sending an email to webminister@drachenwald.sca.org')
                send_message = None    
    
            state = 4

    return render_template(
        'recommend_{}.html'.format(state),
        data=data
    )


#
# JSON API
#

class SQLite3RowEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, sqlite3.Row):
            return dict(obj)
        return super().default(self, obj)


def api_read_table(c, table):
    query = 'SELECT * FROM {}'.format(table)
    c.execute(query)

    return json.dumps(
        {r['id']: r for r in c.fetchall()}, cls=SQLite3RowEncoder
    )


def api_create_row(c, table, data):
    if 'id' in data:
        raise ValueError

    query = 'INSERT INTO {} ({}) VALUES ({})'.format(
        table,
        ', '.join(data),
        ', '.join(':{}'.format(k) for k in data)
    )

    c.execute(query, data)
    return json.dumps({'id': c.lastrowid})


def api_read_row(c, table, id):
    query = 'SELECT * FROM {} WHERE id = ?'.format(table)
    c.execute(query, (id,))
    return json.dumps(c.fetchone(), cls=SQLite3RowEncoder)


def api_update_row(c, table, id, data):
    if 'id' in data:
        raise ValueError
    data['id'] = id

    query = 'UPDATE {} SET {} WHERE id = :id'.format(
        table,
        ', '.join('{} = :{}'.format(k, k) for k in data)
    )

    c.execute(query, data)


def api_delete_row(c, table, id):
    query = 'DELETE FROM {} WHERE id = ?'.format(table)
    c.execute(query, (id,))


def api_list_tables(c):
    query = 'SELECT name FROM sqlite_master WHERE type = "table"'
    c.execute(query)
    return json.dumps([t[0] for t in c.fetchall()])


@app.route('/api/tables', methods=['GET'])
@login_required
def api_tables():
    db = get_db()
    c = db.cursor()
    return Response(api_list_tables(c), mimetype='application/json')


@app.route('/api/<table>', methods=['GET', 'POST'])
@login_required
def api_table(table):
    db = get_db()
    c = db.cursor()

    if request.method == 'GET':
        # retrieve a table
        return Response(api_read_table(c, table), mimetype='application/json')
    elif request.method == 'POST':
        # create a row
        with db:
            return Response(
                api_create_row(c, table, request.get_json()),
                mimetype='application/json'
            )
    else:
        # should not happen
        raise ValueError


@app.route('/api/<table>/<int:id>', methods=['GET', 'PATCH', 'DELETE'])
@login_required
def api_table_id(table, id):
    db = get_db()
    c = db.cursor()

    if request.method == 'GET':
        # retrieve a row
        return Response(api_read_row(c, table, id), mimetype='application/json')
    elif request.method == 'PATCH':
        # update a row
        with db:
            api_update_row(c, table, id, request.get_json())
            return Response(status=200)
    elif request.method == 'DELETE':
        # delete a row
        with db:
            api_delete_row(c, table, id)
            return Response(status=200)
    else:
        # should not happen
        raise ValueError


@app.route('/posthorn/editor')
@login_required
def show_posthorn_editor():
    tables = json.loads(api_list_tables(get_db().cursor()))

    return render_template(
        'editor.html',
        tables=tables,
        model_type='PosthornModel'
    )


@app.route('/signet/editor')
@login_required
def show_signet_editor():
#    tables = json.loads(api_list_tables(get_db().cursor()))
    tables = ['awards', 'scribes', 'scroll_status']

    return render_template(
        'editor.html',
        tables=tables,
        model_type='SignetModel'
    )


if __name__ == '__main__':
    app.run()
