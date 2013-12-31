#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# importations
import webapp2
import re
import os
import time
import jinja2

import logging
import hmac
import random
import string
import hashlib

import urllib
import urllib2
from xml.dom import minidom

from google.appengine.ext import ndb
from google.appengine.api import memcache
import json
import copy
import sys
sys.path.insert(0, 'libs')
from bs4 import BeautifulSoup

# Global variables
template_dir = os.path.join(os.path.dirname(__file__), 'html_template')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir), autoescape = True)

# Databases
class Apps(ndb.Model):
    name = ndb.StringProperty(required = True)
    link = ndb.StringProperty(required = True)
    description = ndb.TextProperty(required = True)
    created_time = ndb.DateTimeProperty(auto_now_add = True)
    last_modified = ndb.DateTimeProperty(auto_now = True)

class Class(ndb.Model):
    subject = ndb.StringProperty(required = True)
    catalog_num = ndb.StringProperty(required = True)
    class_num = ndb.IntegerProperty(required = True)
    comp_sec = ndb.StringProperty(required = True)
    camp_loc = ndb.StringProperty(required = True)
    assoc_class = ndb.IntegerProperty(required = False)
    rel1 = ndb.IntegerProperty(required = False)
    rel2 = ndb.IntegerProperty(required = False)
    enrol_cap = ndb.IntegerProperty(required = False)
    enrol_tot = ndb.IntegerProperty(required = False)
    wait_cap = ndb.IntegerProperty(required = False)
    wait_tot = ndb.IntegerProperty(required = False)
    time_data = ndb.TextProperty(required = False)
    bldg_room = ndb.StringProperty(required = False)
    instructor = ndb.StringProperty(required = False)
    note = ndb.TextProperty(required = False, repeated = True)

class Course(ndb.Model):
    subject = ndb.StringProperty(required = True)
    catalog_num = ndb.StringProperty(required = True)
    units = ndb.FloatProperty(required = True)
    title = ndb.StringProperty(required = True)
    note = ndb.StringProperty(required = False)
    #classes = ndb.StructuredProperty(Class, repeated = True)
    created_time = ndb.DateTimeProperty(auto_now_add = True)
    last_modified = ndb.DateTimeProperty(auto_now = True)

# Basic Handler
class ECEHandle(webapp2.RequestHandler):
    # rewrite the write, more neat
    def write(self, *a, **kw):
        self.response.write(*a, **kw)
    # render helper function, use jinja2 to get template
    def render_str(self, template, **params):
        t = jinja_env.get_template(template)
        return t.render(params)
    # render page using jinja2
    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def set_secure_cookie(self, name, val):
        cookie_val = make_secure_val(val)
        self.response.headers.add_header('Set-Cookie', '%s=%s; Path=/' % (name, cookie_val))

    def read_secure_cookie(self, name):
        cookie_val = self.request.cookies.get(name)
        if cookie_val == None:
            return None
        else:
            return check_secure_val(cookie_val)

    ## login means set the cookie
    def login(self, user):
        self.set_secure_cookie('user_id', str(user.key().id()))

    ## logout means clear the cookie
    def logout(self):
        self.response.headers.add_header('Set-Cookie', 'user_id=; Path=/')

# Handlers
class HomePage(ECEHandle):
    def get(self):
        apps = ndb.gql("SELECT * FROM Apps")
        self.render('homepage.html', apps = apps)
class AddApp(ECEHandle):
    referer = ""
    def render_page(self):
        self.render('add-apps-form.html', referer = self.referer)
    def post(self):
        name = self.request.get('name')
        link = self.request.get('link')
        description = self.request.get('description')

        Apps(key_name = name, 
             name = name, 
             link = link,
             description = description).put()
        self.redirect(str(self.referer))
    def get(self):
        # initialize referer, keep the origin referer
        if not self.request.referer == self.request.url:
            self.referer = self.request.referer
        else: 
            self.referer = self.referer
        self.render_page()


class CourseEnrolmentNotifier(ECEHandle):
    level = ""
    sess = ""
    subject = ""
    cournum = ""
    term_dic = {}
    sess_values = []
    subject_values = []
    def readQueryFrontPage(self, url):
        try:
            content = urllib2.urlopen(url).read()
        except urllib2.URLError:
            return
        if content:
            self.term_dic.clear()
            del self.sess_values[:]
            del self.subject_values[:]
            soup = BeautifulSoup(content)
            # get the term description
            # termDescp should like u'1135=Spring 2013, 1139=Fall 2013, 1141=Winter 2014, 1145=Spring 2014'
            termDescp = soup.input.get_text()
            first_parentheses = termDescp.find("(", 3)
            next_paentheses = termDescp.find(")", first_parentheses + 1)
            termDescp = termDescp[first_parentheses + 1:next_paentheses]

            # assign term_dic
            # term_dic should like this:
            # {u'1135': u'Spring 2013', u'1139': u'Fall 2013',u'1141': u'Winter 2014', u'1145': u'Spring 2014'}
            term_list = termDescp.split(", ")
            for term in term_list:
                term_id, term_descp = term.split("=")
                self.term_dic[term_id] = term_descp

            # sess
            sess = soup.find_all("select", {"name" : "sess"})
            sess = BeautifulSoup(str(sess[0]))
            # sess_selected = <option selected="" value="1141">1141 <option value="1145">1145 </option></option>
            sess_selected = BeautifulSoup(str(sess.find_all(selected=True)))
            sess_selected = sess_selected.option['value'] # sess_selected =  u'1141'
            # sess_values:
            # [[u'1135', False],
            #  [u'1139', False],
            #  [u'1141', True],
            #  [u'1145', False]]
            for se in sess.strings:
                se = se[:se.find('\n')]
                if se == u'':
                    continue
                elif se == sess_selected:
                    self.sess_values.append([se, True])
                else:
                    self.sess_values.append([se, False])
            # subject
            subject = soup.find_all("select", {"name" : "subject"})
            subject = BeautifulSoup(str(subject[0]))
            for su in subject.strings:
                su = su[:su.find('\n')]
                if su == u'':
                    continue
                else:
                    self.subject_values.append(su)
            return True
        else:
            return False

    def render_front_page(self, sess_values = "", term_dic = "", subject_values = ""):
        self.render('/course-enrol/cen-front.html', sess_values = sess_values, term_dic = term_dic, subject_values = subject_values)
    def get(self):
        scheduleURL = "http://www.adm.uwaterloo.ca/infocour/CIR/SA/%s.html"
        graduateSampleURL = scheduleURL % "grad"
        if self.readQueryFrontPage(graduateSampleURL):
            self.render_front_page(self.sess_values, self.term_dic, self.subject_values)

    # consumes table, subject, catalog_num and return list of Class instances
    def readClasses(self, table, id, subject, catalog_num):
        class_num = None
        comp_sec = ""
        camp_loc = ""
        assoc_class = None
        rel1 = None
        rel2 = None
        enrol_cap = 0
        enrol_tot = 0
        wait_cap = 0
        wait_tot = 0
        time_data = ""
        bldg_room = ""
        instructor = ""

        lenOfChildren = len(list(table.children))
        row = 0
        while row < lenOfChildren:
            # escape end line
            tr = table.contents[row]
            if tr == u'\n':
                row += 1
                continue
            elif len(list(tr.children)) == 27 and str(tr.get_text().strip().split()[0]) == 'Class':
                row += 1
                continue
            #elif 9 < len(list(tr.children)) <= 13 and str(tr.get_text().strip().split()[0]).isdigit():
            elif 9 < len(list(tr.children)) <= 13:
                if tr.contents[0].get_text().strip() == u'':
                    c = Class.get_by_id(id + "." + str(class_num))
                    if not tr.contents[10].get_text().strip() == u'':
                        c.time_data += '\n' + str('\n'.join(s.strip() for s in tr.contents[10].strings))
                        c.put()
                    try:
                        if not tr.contents[11].get_text().strip() == u'':
                            c.bldg_room += '\n' + str(tr.contents[11].string.strip())
                            c.put()
                    except:
                        row += 1
                        continue
                    try:
                        if not tr.contents[12].get_text().strip() == u'':
                            c.instructor += '\n' + str(tr.contents[12].string.strip())
                            c.put()
                    except:
                        row += 1
                        continue
                    row += 1
                    continue
                class_num = None
                comp_sec = ""
                camp_loc = ""
                assoc_class = None
                rel1 = None
                rel2 = None
                enrol_cap = 0
                enrol_tot = 0
                wait_cap = 0
                wait_tot = 0
                time_data = ""
                bldg_room = ""
                instructor = ""
                try:
                    class_num = int(tr.contents[0].string.strip())
                except:
                    class_num = None
                try:
                    comp_sec = str(tr.contents[1].string.strip())
                except:
                    comp_sec = None
                try:
                    camp_loc = str(tr.contents[2].string.strip())
                except:
                    camp_loc = None
                try:
                    assoc_class = int(tr.contents[3].string.strip())
                except:
                    assoc_class = None
                try:
                    rel1 = int(tr.contents[4].string.strip())
                except:
                    rel1 = None
                try:
                    rel2 = int(tr.contents[5].string.strip())
                except:
                    rel2 = None
                try:
                    enrol_cap = int(tr.contents[6].string.strip())
                except:
                    enrol_cap = None
                try:
                    enrol_tot = int(tr.contents[7].string.strip())
                except:
                    enrol_tot = None
                try:
                    wait_cap = int(tr.contents[8].string.strip())
                except:
                    wait_cap = None
                try:
                    wait_tot = int(tr.contents[9].string.strip())
                except:
                    wait_tot = None
                try:
                    if not tr.contents[10].br == None:
                        time_data = str('\n'.join(s.strip() for s in tr.contents[10].strings))
                    else:
                        time_data = str(tr.contents[10].string.strip())
                except:
                    time_data = None
                try:
                    bldg_room = str(tr.contents[11].string.strip())
                except:
                    bldg_room = None
                try:
                    instructor = str(tr.contents[12].string.strip())
                except:
                    instructor = None
                Class(id = id + "." + str(class_num),
                      subject = subject,
                      catalog_num = catalog_num,
                      class_num = class_num,
                      comp_sec = comp_sec,
                      camp_loc = camp_loc,
                      assoc_class = assoc_class,
                      rel1 = rel1,
                      rel2 = rel2,
                      enrol_cap = enrol_cap,
                      enrol_tot = enrol_tot,
                      wait_cap = wait_cap,
                      wait_tot = wait_tot,
                      time_data = time_data,
                      bldg_room = bldg_room,
                      instructor = instructor,
                      note = []).put()
                row += 1
            # need revise
            elif len(list(tr.children)) < 9 and (not tr.i == None):
                c = Class.get_by_id(id + "." + str(class_num))
                c.note.append(str(tr.i.string.strip()))
                c.put()
                row += 1
            else:
                row += 1
                continue
        return True

    def readCourses(self, table):
        subject = ""
        catalog_num = ""
        units = None
        title = ""
        note = ""

        lenOfChildren = len(list(table.children))
        row = 0
        while row < lenOfChildren:
            # escape end line
            tr = table.contents[row]
            if tr == u'\n':
                row += 1
                continue
            # course head row
            elif len(list(tr.children)) == 8 and str(tr.get_text().strip().split()[0]) == str(self.subject):
                #clear old data
                subject = ""
                catalog_num = None
                units = None
                title = ""
                # set new data
                try:
                    subject = str(tr.contents[0].string.strip())
                except:
                    subject = ""
                try:
                    catalog_num = str(tr.contents[2].string.strip())
                except:
                    catalog_num = ""
                try:
                    units = float(tr.contents[4].string.strip())
                except:
                    units = None
                try:
                    title = str(tr.contents[6].string.strip())
                except:
                    title = ""
                row += 1
            elif len(list(tr.children)) == 1 and (not tr.get_text().strip() == u'') and tr.get_text().strip().split()[0] == u'Notes:':
                note = ""
                try:
                    note = str(tr.get_text().strip())
                except:
                    note = None
                row += 1
            elif len(list(tr.children)) == 2 and (not tr.table == None):
                Course(id = subject + "." + str(catalog_num), 
                       subject = subject, 
                       catalog_num = catalog_num, 
                       units = units,
                       title = title, 
                       note = note).put()
                if self.readClasses(tr.table, subject + "." + catalog_num, subject, catalog_num):
                    row += 1
                    continue
                else:
                    return False
            else:
                row += 1
                continue
        return True

    def readQueryResult(self, query_url, query_obj):
        try:
            query_result = urllib2.urlopen(query_url, query_obj).read()
        except urllib2.URLError:
            return
        if query_result:
            soup = BeautifulSoup(query_result)
            table = soup.table
            if table:
                if self.readCourses(table):
                    return True
                else:
                    return False
            else:
                self.write("Sorry, but your query had no matches.")
        else:
            return False
    def post(self):
        query_url = "http://www.adm.uwaterloo.ca/cgi-bin/cgiwrap/infocour/salook.pl"
        # produce query_object
        self.level = self.request.get('level')
        self.sess = self.request.get('sess')
        self.subject = self.request.get('subject')
        self.cournum = self.request.get('cournum')
        query_dic = {}
        query_dic['level'] = self.level
        query_dic['sess'] = self.sess
        query_dic['subject'] = self.subject
        query_dic['cournum'] = self.cournum
        query_obj = urllib.urlencode(query_dic)
        # read query result
        if self.readQueryResult(query_url, query_obj):
            self.write("success!")
        else:
            self.write("Failed!")

class FlushCourseClass(ECEHandle):
    def get(self):
        ndb.delete_multi(Course.query().fetch(keys_only=True))
        ndb.delete_multi(Class.query().fetch(keys_only=True))
        self.write("Course&Class Database are flushed successfully!")
# control = True
# count = 0        
# class Test(ECEHandle):
#     # def get(self):
#     #     global control
#     #     global count
#     #     while control:
#     #         count += 1
#     #         time.sleep(0.5)
#     #     self.write(count)
#     def get(self):
#         # global control
#         # control = False
#         time = 10
#         while time > 0:
#             result = urllib2.urlopen('http://localhost:10080/course-reminder')
#             time -= 1
#         self.write(count)


app = webapp2.WSGIApplication([
    ('/?', HomePage),
    ('/add-app', AddApp),
    ('/uw-cen/?', CourseEnrolmentNotifier),
    ('/uw-cen/flush', FlushCourseClass)
    #('/test', Test)
], debug=True)
