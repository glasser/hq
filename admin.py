#!/usr/bin/env python2.5
import model
import handler

class FamilyListHandler(handler.RequestHandler):
  def get(self):
    families = model.TagFamily.all()
    self.render_template("families", {
      "families": families
    })


class FamilyCreateHandler(handler.RequestHandler):
  def post(self):
    name = model.CanonicalizeTagName(self.request.get('name'))
    # TODO(glasser): Better error handling.
    model.TagFamily.get_or_insert(name)
    self.redirect(FamilyListHandler.get_url())


class FamilyOptionCreateHandler(handler.RequestHandler):
  def post(self, family_name):
    family_name = model.CanonicalizeTagName(family_name)
    family = model.TagFamily.get_by_key_name(family_name)
    # TODO(glasser): Better error handling.
    assert family is not None
    option = model.CanonicalizeTagName(self.request.get('option'))
    # TODO(glasser): Technically this is an unlocked read-modify-write
    # and there could be a race condition; in this particular
    # admin-only case I'm going to lean towards the impact being
    # marginal.
    if option not in family.options:
      family.options.append(option)
    # TODO(glasser): Better error handling.
    family.put()
    self.redirect(FamilyListHandler.get_url())


class FamilyOptionDeleteHandler(handler.RequestHandler):
  def get(self, family_name, option):
    family_name = model.CanonicalizeTagName(family_name)
    option = model.CanonicalizeTagName(option)
    family = model.TagFamily.get_by_key_name(family_name)
    # TODO(glasser): Better error handling.
    assert family is not None
    # TODO(glasser): Check whether any puzzle has the tag before
    # deleting?
    family.options.remove(option)
    # TODO(glasser): Better error handling.
    family.put()
    self.redirect(FamilyListHandler.get_url())


class FamilyDeleteHandler(handler.RequestHandler):
  def get(self, family_name):
    family_name = model.CanonicalizeTagName(family_name)
    family = model.TagFamily.get_by_key_name(family_name)
    # TODO(glasser): Better error handling.
    assert family is not None
    # TODO(glasser): Better error handling.
    assert not family.options
    family.delete()
    self.redirect(FamilyListHandler.get_url())


class BannerListHandler(handler.RequestHandler):
  def get(self):
    banners = model.Banner.all()
    self.render_template("banners", {
      "banners": banners,
    })


class BannerAddHandler(handler.RequestHandler):
  def post(self):
    contents = self.request.get('contents')
    # TODO(glasser): Better error handling.
    assert contents
    banner = model.Banner(contents=contents)
    banner.put()
    self.redirect(BannerListHandler.get_url())

class BannerDeleteHandler(handler.RequestHandler):
  def get(self, banner_id):
    banner = model.Banner.get_by_id(long(banner_id))
    # TODO(glasser): Better error handling.
    assert banner is not None
    banner.delete()
    self.redirect(BannerListHandler.get_url())


HANDLERS = [
    ('/admin/tags/?', FamilyListHandler),
    ('/admin/tags/add-option/(%s)/?' % model.TAG_PIECE,
     FamilyOptionCreateHandler),
    ('/admin/tags/delete-option/(%s)/(%s)/?'
     % (model.TAG_PIECE, model.TAG_PIECE), FamilyOptionDeleteHandler),
    ('/admin/tags/add/?', FamilyCreateHandler),
    ('/admin/tags/delete/(%s)/?' % model.TAG_PIECE, FamilyDeleteHandler),
    ('/admin/banners/?', BannerListHandler),
    ('/admin/banners/add/?', BannerAddHandler),
    ('/admin/banners/delete/(\\d+)/?', BannerDeleteHandler),
]
