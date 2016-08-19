# -*- coding: utf8 -*-
import json
from django.template.response import TemplateResponse
from django.http.response import HttpResponse, JsonResponse
from django.db.models import Q
from django import forms, http
from django.conf import settings

from www.views import AuthedView, LeftSideBarMixin, BaseView
from www.decorator import perm_required
from www.models import TenantServicesPort, TenantServiceEnvVar
from www.service_http import RegionServiceApi
from www.utils.crypt import make_uuid
from www.servicetype import ServiceType

from www.models import AppService, AppServiceEnv, AppServicePort, \
    TenantServiceRelation, AppServiceRelation, ServiceExtendMethod, \
    TenantServiceVolume, AppServiceVolume, TenantServiceInfo, \
    AppServiceExtend, AppServiceShareInfo, AppServiceImages

import logging

logger = logging.getLogger('default')
regionClient = RegionServiceApi()


class ShareServiceStep1View(LeftSideBarMixin, AuthedView):
    """ 服务分享概览页面 """
    def get_context(self):
        context = super(ShareServiceStep1View, self).get_context()
        return context
 
    @perm_required('app_publish')
    def get(self, request, *args, **kwargs):
        context = self.get_context()
        context["myAppStatus"] = "active"
        # 端口信息
        port_list = TenantServicesPort.objects.filter(service_id=self.service.service_id).\
            values('container_port', 'protocol', 'port_alias', 'is_inner_service', 'is_outer_service')
        context["port_list"] = list(port_list)
        # 环境变量
        used_port = [x["container_port"] for x in port_list]
        env_list = TenantServiceEnvVar.objects.filter(service_id=self.service.service_id)\
            .exclude(container_port__in=used_port)\
            .values('container_port', 'name', 'attr_name', 'attr_value', 'is_change', 'scope')
        context["env_list"] = list(env_list)
        # 持久化目录
        result_list = []
        if self.service.category == "application":
            volume_list = TenantServiceVolume.objects.filter(service_id=self.service.service_id)
            for volume in list(volume_list):
                tmp_path = volume.volume_path
                if tmp_path:
                    volume.volume_path = tmp_path.replace("/app/", "", 1)
                result_list.append(volume)
        context["volume_list"] = result_list
        # 依赖应用
        dep_service_ids = TenantServiceRelation.objects.filter(service_id=self.service.service_id).values("dep_service_id")
        dep_service_list = TenantServiceInfo.objects.filter(service_id__in=dep_service_ids)\
            .values("service_key", "version", "service_alias", "service_type")
        context["dep_service_list"] = dep_service_list
        # 检查依赖服务是否已经发布
        if len(dep_service_list) > 0:
            for dep_service in list(dep_service_list):
                if dep_service.service_key == "application":
                    context["dep_service_name"] = dep_service.service_alias
                    context["dep_status"] = False
                    break
                count = AppService.objects.filter(service_key=dep_service.service_key, app_version=dep_service.version).count()
                if count == 0:
                    context["dep_status"] = False
                    context["dep_service_name"] = dep_service.service_alias
                    break

        # 内存、节点
        context["memory"] = self.service.min_memory
        context["node"] = self.service.min_node
        #
        context["tenant_name"] = self.tenantName
        context["service_alias"] = self.serviceAlias
        # 返回页面
        return TemplateResponse(request,
                                'www/service/share_step_1.html',
                                context)


class ShareServiceStep2View(LeftSideBarMixin, AuthedView):
    """服务分享step2:获取环境变量是否可修改"""
    def get_context(self):
        context = super(ShareServiceStep2View, self).get_context()
        return context

    @perm_required('app_publish')
    def get(self, request, *args, **kwargs):
        # 获取服务的环境变量
        context = self.get_context()
        context["myAppStatus"] = "active"
        port_list = TenantServicesPort.objects.filter(service_id=self.service.service_id)\
            .values_list('container_port', flat=True)
        env_list = TenantServiceEnvVar.objects.filter(service_id=self.service.service_id)\
            .exclude(container_port__in=list(port_list))\
            .values('ID', 'container_port', 'name', 'attr_name', 'attr_value', 'is_change', 'scope')
        env_ids = [str(x["ID"]) for x in list(env_list)]
        if len(env_ids) == 0:
            return self.redirect_to("/apps/{0}/{1}/share/step3".format(self.tenantName, self.serviceAlias))

        context["env_ids"] = ",".join(env_ids)
        context["env_list"] = list(env_list)
        # path param
        context["tenant_name"] = self.tenantName
        context["service_alias"] = self.serviceAlias
        # 返回页面
        return TemplateResponse(request,
                                'www/service/share_step_2.html',
                                context)

    @perm_required('app_publish')
    def post(self, request, *args, **kwargs):
        # 服务的环境是否可修改存储
        post_data = request.POST.dict()
        env_ids = post_data.get('env_ids')
        logger.info("env_ids={}".format(env_ids))
        # clear old info
        AppServiceShareInfo.objects.filter(tenant_id=self.service.tenant_id,
                                           service_id=self.service.service_id).delete()
        if env_ids != "" and env_ids is not None:
            env_data = []
            tmp_id_list = env_ids.split(",")
            for tmp_id in tmp_id_list:
                is_change = post_data.get(tmp_id, False)
                app_env = AppServiceShareInfo(tenant_id=self.service.tenant_id,
                                              service_id=self.service.service_id,
                                              tenant_env_id=int(tmp_id),
                                              is_change=is_change)
                env_data.append(app_env)
            # add new info
            if len(env_data) > 0:
                AppServiceShareInfo.objects.bulk_create(env_data)
        logger.debug(u'publish.service. now add publish service env ok')
        return self.redirect_to('/apps/{0}/{1}/share/step3'.format(self.tenantName, self.serviceAlias))


class ShareServiceStep3View(LeftSideBarMixin, AuthedView):
    """ 服务关系配置页面 """
    def get_context(self):
        context = super(ShareServiceStep3View, self).get_context()
        return context

    @perm_required('app_publish')
    def get(self, request, *args, **kwargs):
        # 跳转到服务关系发布页面
        context = self.get_context()
        context["myAppStatus"] = "active"
        app = {
            "tenant_id": self.service.tenant_id,
            "service_id": self.service.service_id,
            "app_alias": self.service.service_alias,
            "desc": self.service.desc,
            # "info": "",
            # "logo": "",
            # "category_first": 0,
            # "category_second": 0,
            # "category_third": 0,
            # "url_site": "",
            # "url_source": "",
            # "url_demo": "",
            # "url_feedback": "",
            # "app_version": "",
            # "release_note": "",
            # "is_outer": False,
            "service_key": make_uuid(self.serviceAlias),
        }
        # 获取之前发布的服务
        pre_app = AppService.objects.filter(service_id=self.service.service_id).order_by('-ID')[:1]
        if len(pre_app) == 1:
            first_app = list(pre_app)[0]
            app["app_alias"] = first_app.app_alias
            app["desc"] = first_app.desc
            app["info"] = first_app.info
            app["logo"] = first_app.logo
            if first_app.show_category:
                first, second, third = first_app.show_category.split(",")
                app["category_first"] = first
                app["category_second"] = second
                app["category_third"] = third

            try:
                extend_info = AppServiceExtend.objects.get(service_key=first_app.service_key,
                                                           app_version=first_app.app_version)
                app["url_site"] = extend_info.url_site
                app["url_source"] = extend_info.url_source
                app["url_demo"] = extend_info.url_demo
                app["url_feedback"] = extend_info.url_feedback
                app["release_note"] = extend_info.release_note
            except AppServiceExtend.DoesNotExist:
                logger.error("[share service] extend info query error!")

            app["service_key"] = first_app.service_key
            app["app_version"] = first_app.app_version
            app["is_outer"] = first_app.is_outer

        context["data"] = app
        # path param
        context["tenant_name"] = self.tenantName
        context["service_alias"] = self.serviceAlias
        state = request.GET.get("state")
        if state is not None:
            context["state"] = state
        # 返回页面
        return TemplateResponse(request,
                                'www/service/share_step_3.html',
                                context)

    # form提交.
    @perm_required('app_publish')
    def post(self, request, *args, **kwargs):
        # 获取form表单
        form_data = ShareServiceForm(request.POST, request.FILES)
        if not form_data.is_valid():
            self.redirect_to('/apps/{0}/{1}/share/step3?state={2}'.format(self.tenantName, self.serviceAlias, 1))
        # 服务基础信息
        service_key = form_data.cleaned_data['service_key']
        app_version = form_data.cleaned_data['app_version']

        # 获取服务基本信息
        url_site = form_data.cleaned_data['url_site']
        url_source = form_data.cleaned_data['url_source']
        url_demo = form_data.cleaned_data['url_demo']
        url_feedback = form_data.cleaned_data['url_feedback']
        release_note = form_data.cleaned_data['release_note']
        # 判断是否需要重新添加
        count = AppServiceExtend.objects.filter(service_key=service_key, app_version=app_version).count()
        if count == 0:
            extend_info = AppServiceExtend(service_key=service_key,
                                           app_version=app_version,
                                           url_site=url_site,
                                           url_source=url_source,
                                           url_demo=url_demo,
                                           url_feedback=url_feedback,
                                           release_note=release_note.strip())
            extend_info.save()
        else:
            AppServiceExtend.objects.filter(service_key=service_key, app_version=app_version)\
                .update(url_site=url_site,
                        url_source=url_source,
                        url_demo=url_demo,
                        url_feedback=url_feedback,
                        release_note=release_note.strip())
        # 基础信息
        app_alias = form_data.cleaned_data['app_alias']
        logo = None
        try:
            image = AppServiceImages.objects.get(service_id=self.service.service_id)
            logo = image.logo
        except AppServiceImages.DoesNotExist:
            pass

        info = form_data.cleaned_data['info']
        desc = form_data.cleaned_data['desc']
        category_first = form_data.cleaned_data['category_first']
        category_second = form_data.cleaned_data['category_second']
        category_third = form_data.cleaned_data['category_third']
        is_outer = form_data.cleaned_data['is_outer']
        # count = AppService.objects.filter(service_key=service_key, app_version=app_version).count()
        # if count == 0:
        try:
            app = AppService.objects.get(service_key=service_key, app_version=app_version)
            app.app_alias = app_alias
            if logo is not None:
                app.logo = logo
            app.info = info
            app.desc = desc
            app.show_category = '{},{},{}'.format(category_first, category_second, category_third)
            app.is_outer = is_outer
        except AppService.DoesNotExist:
            app = AppService(
                tenant_id=self.service.tenant_id,
                service_id=self.service.service_id,
                service_key=service_key,
                app_version=app_version,
                app_alias=app_alias,
                creater=self.user.pk,
                info=info,
                desc=desc,
                status='',
                category="app_publish",
                is_service=self.service.is_service,
                is_web_service=self.service.is_web_service,
                image=self.service.image,
                namespace=settings.CLOUD_ASSISTANT,
                slug='',
                extend_method=self.service.extend_method,
                cmd=self.service.cmd,
                env=self.service.env,
                min_node=self.service.min_node,
                min_cpu=self.service.min_cpu,
                min_memory=self.service.min_memory,
                inner_port=self.service.inner_port,
                volume_mount_path=self.service.volume_mount_path,
                service_type='application',
                is_init_accout=False,
                show_category='{},{},{}'.format(category_first, category_second, category_third),
                is_base=False,
                is_outer=is_outer,
                publisher=self.user.email,
                is_ok=0)
            if logo is not None:
                app.logo = logo
            if app.is_slug():
                app.slug = '/app_publish/{0}/{1}.tgz'.format(app.service_key, app.app_version)
        # save
        app.dest_yb = False
        app.dest_ys = False
        app.save()
        # 保存port
        # port 1 delete all old info
        AppServicePort.objects.filter(service_key=service_key, app_version=app_version).delete()
        # query new port
        port_list = AppServicePort.objects.filter(service_key=service_key,
                                                  app_version=app_version)\
            .values('container_port', 'protocol', 'port_alias', 'is_inner_service', 'is_outer_service')
        port_data = []
        for port in list(port_list):
            app_port = AppServicePort(service_key=service_key,
                                      app_version=app_version,
                                      container_port=port.container_port,
                                      protocol=port.protocol,
                                      port_alias=port.port_alias,
                                      is_inner_service=port.is_inner_service,
                                      is_outer_service=port.is_outer_service)
            port_data.append(app_port)
        if len(port_data) > 0:
            logger.debug(len(port_data))
            AppServicePort.objects.bulk_create(port_data)
        logger.debug(u'share.service. now add shared service port ok')
        # 保存env
        AppServiceEnv.objects.filter(service_key=service_key, app_version=app_version).delete()
        export = [x["container_port"] for x in list(port_list)]
        env_list = TenantServiceEnvVar.objects.filter(service_id=self.service.service_id)\
            .exclude(container_port__in=export)\
            .values('ID', 'container_port', 'name', 'attr_name', 'attr_value', 'is_change', 'scope')
        share_info_list = AppServiceShareInfo.objects.filter(service_id=self.service.service_id)\
            .values("tenant_env_id", "is_change")
        share_info_map = {x["tenant_env_id"]: x["is_change"] for x in list(share_info_list)}
        env_data = []
        for env in list(env_list):
            is_change = env["is_change"]
            if env["ID"] in share_info_map.keys():
                is_change = share_info_map.get(env["ID"])
            app_env = AppServiceEnv(service_key=service_key,
                                    app_version=app_version,
                                    name=env["name"],
                                    attr_name=env["attr_name"],
                                    attr_value=env["attr_value"],
                                    scope=env["scope"],
                                    is_change=is_change,
                                    container_port=env["container_port"])
            env_data.append(app_env)
        if len(env_data) > 0:
            logger.debug(len(env_data))
            AppServiceEnv.objects.bulk_create(env_data)
        logger.debug(u'share.service. now add shared service env ok')

        # 保存extend_info
        count = ServiceExtendMethod.objects.filter(service_key=service_key, app_version=app_version).count()
        if count == 0:
            extend_method = ServiceExtendMethod(
                service_key=service_key,
                app_version=app_version,
                min_node=self.service.min_node,
                max_node=20,
                step_node=1,
                min_memory=self.service.min_memory,
                max_memory=65536,
                step_memory=128,
                is_restart=False)
            extend_method.save()
        else:
            ServiceExtendMethod.objects.filter(service_key=service_key, app_version=app_version)\
                .update(min_node=self.service.min_node, min_memory=self.service.min_memory)
        logger.debug(u'share.service. now add shared service extend method ok')

        # 保存持久化设置
        if self.service.category == "application":
            volume_list = TenantServiceVolume.objects.filter(service_id=self.service.service_id)
            volume_data = []
            AppServiceVolume.objects.filter(service_key=service_key,
                                            app_version=app_version).delete()
            for volume in list(volume_list):
                app_volume = AppServiceVolume(service_key=service_key,
                                              app_version=app_version,
                                              category=volume.category,
                                              volume_path=volume.volume_path)
                volume_data.append(app_volume)
            if len(volume_data) > 0:
                logger.debug(len(volume_data))
                AppServiceVolume.objects.bulk_create(volume_data)
        logger.debug(u'share.service. now add share service volume ok')
        # 服务依赖关系
        AppServiceRelation.objects.filter(service_key=service_key,
                                          app_version=app_version).delete()
        relation_list = TenantServiceRelation.objects.filter(service_id=self.service.service_id)
        dep_service_ids = [x["dep_service_id"] for x in relation_list]
        dep_service_list = TenantServiceInfo.objects.filter(service_id__in=dep_service_ids)
        app_relation_list = []
        if len(dep_service_list) > 0:
            for dep_service in list(dep_service_list):
                if dep_service.service_key == "application":
                    logger.error("dep service is application not published")
                    raise http.Http404
                relation = AppServiceRelation(service_key=service_key,
                                              app_version=app_version,
                                              app_alias=app_alias,
                                              dep_service_key=dep_service.service_key,
                                              dep_app_version=dep_service.version,
                                              dep_app_alias=dep_service.service_alias)
                app_relation_list.append(relation)
        if len(app_relation_list) > 0:
            logger.debug(len(app_relation_list))
            AppServiceRelation.objects.bulk_create(app_relation_list)
        # region发送请求
        if app.is_slug():
            self.upload_slug(app)
        elif app.is_image():
            self.upload_image(app)
        return self.redirect_to('/apps/{0}/{1}/detail/'.format(self.tenantName, self.serviceAlias))

    def _create_publish_event(self, info):
        template = {
            "user_id": self.user.nick_name,
            "tenant_id": self.service.tenant_id,
            "service_id": self.service.service_id,
            "type": "publish",
            "desc": info + u"应用发布中...",
            "show": True,
        }
        try:
            body = regionClient.create_event(self.service.service_region, json.dumps(template))
            return body.event_id
        except Exception as e:
            logger.exception("service.publish", e)
            return None

    def upload_slug(self, app):
        """ 上传slug包 """
        oss_upload_task = {
            "service_key": app.service_key,
            "app_version": app.app_version,
            "service_id": self.service.service_id,
            "deploy_version": self.service.deploy_version,
            "tenant_id": self.service.tenant_id,
            "action": "create_new_version",
            "is_outer": app.is_outer,
        }
        try:
            # 生成发布事件
            event_id = self._create_publish_event(u"云帮")
            oss_upload_task.update({"dest" : "yb", "event_id" : event_id})
            regionClient.send_task(self.service.service_region, 'app_slug', json.dumps(oss_upload_task))
            if app.is_outer:
                event_id = self._create_publish_event(u"云市")
                oss_upload_task.update({"dest" : "ys", "event_id" : event_id})
                regionClient.send_task(self.service.service_region, 'app_slug', json.dumps(oss_upload_task))
        except Exception as e:
            logger.error("service.publish",
                         "upload_slug for {0}({1}), but an error occurred".format(app.service_key, app.app_version))
            logger.exception("service.publish", e)

    def upload_image(self, app):
        """ 上传image镜像 """
        image_upload_task = {
            "service_key": app.service_key,
            "app_version": app.app_version,
            "action": "create_new_version",
            "image": self.service.image,
            "is_outer": app.is_outer,
        }
        try:
            event_id = self._create_publish_event(u"云帮")
            image_upload_task.update({"dest":"yb", "event_id" : event_id})
            regionClient.send_task(self.service.service_region, 'app_image', json.dumps(image_upload_task))
            if app.is_outer:
                event_id = self._create_publish_event(u"云市")
                image_upload_task.update({"dest":"ys", "event_id" : event_id})
                regionClient.send_task(self.service.service_region, 'app_image', json.dumps(image_upload_task))
        except Exception as e:
            logger.error("service.publish",
                         "upload_image for {0}({1}), but an error occurred".format(app.service_key, app.app_version))
            logger.exception("service.publish", e)


class ShareServiceForm(forms.Form):
    """ 服务发布详情页form """
    app_alias = forms.CharField(help_text=u"应用名称")
    info = forms.CharField(help_text=u"一句话介绍")
    desc = forms.CharField(help_text=u"应用简介")
    category_first = forms.CharField(required=True, help_text=u"分类1")
    category_second = forms.CharField(required=True, help_text=u"分类2")
    category_third = forms.CharField(required=True, help_text=u"分类3")

    url_site = forms.CharField(help_text=u"网站url")
    url_source = forms.CharField(help_text=u"源码url")
    url_demo = forms.CharField(help_text=u"样例代码url")
    url_feedback = forms.CharField(help_text=u"反馈url")

    service_key = forms.CharField(help_text=u"服务发布key")
    app_version = forms.CharField(help_text=u"版本")
    release_note = forms.CharField(help_text=u"更新说明")
    is_outer = forms.BooleanField(required=False, initial=False, help_text=u"是否发布到云市")


class ShareServiceImageForm(forms.Form):
    """服务截图上传form表单"""
    logo = forms.FileField(help_text=u"应用logo")
    service_id = forms.CharField(help_text=u"服务发布key")


class ShareServiceImageView(BaseView):

    def post(self, request, *args, **kwargs):
        # 获取表单信息
        service_id = request.POST['service_id']
        logo = request.FILES['logo']
        # 更新图片路径
        count = AppServiceImages.objects.filter(service_id=service_id).count()
        if count > 1:
            AppServiceImages.objects.filter(service_id=service_id).delete()
            count = 0
        if count == 0:
            image_info = AppServiceImages()
            image_info.service_id = service_id
            image_info.logo = logo
        else :
            image_info = AppServiceImages.objects.get(service_id=service_id)
            image_info.logo = logo
        image_info.save()
        data = {"success": True, "code": 200, "pic": image_info.logo.name}
        return JsonResponse(data, status=200)

# class ShareServiceUpdateView(LeftSideBarMixin, AuthedView):
#     """更新"""
#     @perm_required('app_publish')
#     def get(self, request, *args, **kwargs):
#         # 跳转到服务关系发布页面
#         context = self.get_context()
#         app = {
#             "alias": self.service.service_alias,
#             "version": self.service.version,
#             "info": '',
#             "desc": self.service.desc,
#             ""
#         }
#         # 返回页面
#         return TemplateResponse(request,
#                                 'www/service/share_step_3.html',
#                                 context)
#
#     # form提交.
#     @perm_required('app_publish')
#     def post(self, request, *args, **kwargs):
#         # todo 需要添加form表单验证
#         try:
#             post_data = request.POST.dict()
#             service_key = post_data.get('service_key')
#             app_version = post_data.get('app_version')
#             logger.debug("service.publish", "post_data is {0}".format(post_data))
#             app = AppService.objects.get(service_key=service_key, app_version=app_version)
#             # 保存当前服务依赖的其他服务
#             relation_list = []
#             pre_fix_string = post_data.get("prefix")
#             logger.info("pre_fix_string={}".format(pre_fix_string))
#             pre_fix_list = pre_fix_string.split(";")
#             if pre_fix_list:
#                 for pre_fix in pre_fix_list:
#                     if pre_fix:
#                         pre_key, pre_version, pre_alias = pre_fix.split(",")
#                         relation = AppServiceRelation(service_key=pre_key.lstrip().rstrip(),
#                                                       app_version=pre_version.lstrip().rstrip(),
#                                                       app_alias=pre_alias.lstrip().rstrip(),
#                                                       dep_service_key=app.service_key,
#                                                       dep_app_version=app.app_version,
#                                                       dep_app_alias=app.app_alias)
#                         relation_list.append(relation)
#             AppServiceRelation.objects.filter(dep_service_key=app.service_key, dep_app_version=app.app_version).delete()
#             # 保存依赖当前服务的发布服务
#             suf_fix_string = post_data.get("suffix")
#             logger.info("pre_fix_string={}".format(suf_fix_string))
#             suf_fix_list = suf_fix_string.split(";")
#             if suf_fix_list:
#                 for suf_fix in suf_fix_list:
#                     if suf_fix:
#                         suf_key, suf_version, suf_alias = suf_fix.split(",")
#                         relation = AppServiceRelation(service_key=app.service_key,
#                                                       app_version=app.app_version,
#                                                       app_alias=app.app_alias,
#                                                       dep_service_key=suf_key.lstrip().rstrip(),
#                                                       dep_app_version=suf_version.lstrip().rstrip(),
#                                                       dep_app_alias=suf_alias.lstrip().rstrip())
#                         relation_list.append(relation)
#             AppServiceRelation.objects.filter(service_key=app.service_key, app_version=app.app_version).delete()
#
#             # 批量增加
#             if len(relation_list) > 0:
#                 AppServiceRelation.objects.bulk_create(relation_list)
#
#             app.dest_yb = False
#             app.dest_ys = False
#             app.save()
#             # 事件
#             if app.is_slug():
#                 self.upload_slug(app)
#             elif app.is_image():
#                 self.upload_image(app)
#
#             return self.redirect_to('/apps/{0}/{1}/detail/'.format(self.tenantName, self.serviceAlias))
#         except Exception as e:
#             logger.exception(e)
#             return HttpResponse(u"发布过程出现异常", status=500)
