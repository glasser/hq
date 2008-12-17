#!/usr/bin/env python2.5

import wsgiref.handlers

from google.appengine.ext import webapp

import admin
import puzzles

def main():
  application = webapp.WSGIApplication(
      admin.HANDLERS + puzzles.HANDLERS,
      debug=True)
  wsgiref.handlers.CGIHandler().run(application)


if __name__ == '__main__':
  main()
