#!/usr/bin/env python
# encoding: utf-8
import re
from lxml import etree
from scrapy import Spider
from scrapy.crawler import CrawlerProcess
from scrapy.selector import Selector
from scrapy.http import Request
from scrapy.utils.project import get_project_settings
from sina.items import TweetsItem, InformationItem, RelationshipsItem, CommentItem
from sina.spiders.utils import time_fix
import time
import uuid
import sina.operation.scrap_info_operation as dataset_operation
import sina.operation.mongodb_operation as mongodb_operation
import sina.operation.mongo_to_mysql as mongo_to_mysql
import datetime
from sina.settings import MAX_INTERVAL, MAX_SCRAP_NUM, MIN_LIKE



class WeiboSpider(Spider):
    name = "weibo_spider"
    base_url = "https://weibo.cn"
    blogger_id = ""
    dataset_id = str(uuid.uuid1())
    total_scrap_num = 0

    def start_requests(self):
        start_uids = [
            # '3176010690'    # 孙狗
            # '1748526937'  # 我自己
            # '2803301701',  # 人民日报
            # '1699432410'  # 新华社
            '6001318807'  # 猫哥
        ]
        dataset_operation.insert_dataset(self.dataset_id)
        for uid in start_uids:
            self.blogger_id = uid
            yield Request(url="https://weibo.cn/%s/info" % uid, callback=self.parse_information)
        # 生成wordpress文章
        mongo_to_mysql.transfer_to_mysql()

    def parse_information(self, response):
        """ 抓取个人信息 """
        information_item = InformationItem()
        information_item['dataset_id'] = self.dataset_id
        information_item['blogger_id'] = self.blogger_id

        # TODO 假如用户已经存在,则删除过去的用户信息
        mongodb_operation.delete_previous_user_info(blogger_id=self.blogger_id, current_dataset_id=self.dataset_id)

        information_item['crawl_time'] = int(time.time())
        selector = Selector(response)
        information_item['_id'] = re.findall('(\d+)/info', response.url)[0]
        text1 = ";".join(selector.xpath('body/div[@class="c"]//text()').extract())  # 获取标签里的所有text()
        nick_name = re.findall('昵称;?[：:]?(.*?);', text1)
        gender = re.findall('性别;?[：:]?(.*?);', text1)
        place = re.findall('地区;?[：:]?(.*?);', text1)
        briefIntroduction = re.findall('简介;?[：:]?(.*?);', text1)
        birthday = re.findall('生日;?[：:]?(.*?);', text1)
        sex_orientation = re.findall('性取向;?[：:]?(.*?);', text1)
        sentiment = re.findall('感情状况;?[：:]?(.*?);', text1)
        vip_level = re.findall('会员等级;?[：:]?(.*?);', text1)
        authentication = re.findall('认证;?[：:]?(.*?);', text1)
        labels = re.findall('标签;?[：:]?(.*?)更多>>', text1)
        if nick_name and nick_name[0]:
            information_item["nick_name"] = nick_name[0].replace(u"\xa0", "")
        if gender and gender[0]:
            information_item["gender"] = gender[0].replace(u"\xa0", "")
        if place and place[0]:
            place = place[0].replace(u"\xa0", "").split(" ")
            information_item["province"] = place[0]
            if len(place) > 1:
                information_item["city"] = place[1]
        if briefIntroduction and briefIntroduction[0]:
            information_item["brief_introduction"] = briefIntroduction[0].replace(u"\xa0", "")
        if birthday and birthday[0]:
            information_item['birthday'] = birthday[0]
        if sex_orientation and sex_orientation[0]:
            if sex_orientation[0].replace(u"\xa0", "") == gender[0]:
                information_item["sex_orientation"] = "同性恋"
            else:
                information_item["sex_orientation"] = "异性恋"
        if sentiment and sentiment[0]:
            information_item["sentiment"] = sentiment[0].replace(u"\xa0", "")
        if vip_level and vip_level[0]:
            information_item["vip_level"] = vip_level[0].replace(u"\xa0", "")
        if authentication and authentication[0]:
            information_item["authentication"] = authentication[0].replace(u"\xa0", "")
        if labels and labels[0]:
            information_item["labels"] = labels[0].replace(u"\xa0", ",").replace(';', '').strip(',')
        request_meta = response.meta
        request_meta['item'] = information_item
        yield Request(self.base_url + '/u/{}'.format(information_item['_id']),
                      callback=self.parse_further_information,
                      meta=request_meta, dont_filter=True, priority=1)

    def parse_further_information(self, response):
        text = response.text
        information_item = response.meta['item']
        tweets_num = re.findall('微博\[(\d+)\]', text)
        if tweets_num:
            information_item['tweets_num'] = int(tweets_num[0])
        follows_num = re.findall('关注\[(\d+)\]', text)
        if follows_num:
            information_item['follows_num'] = int(follows_num[0])
        fans_num = re.findall('粉丝\[(\d+)\]', text)
        if fans_num:
            information_item['fans_num'] = int(fans_num[0])
        yield information_item

        # 获取该用户微博
        yield Request(url=self.base_url + '/{}/profile?page=1'.format(information_item['_id']),
                      callback=self.parse_tweet,
                      priority=1)

        # 获取关注列表
        # yield Request(url=self.base_url + '/{}/follow?page=1'.format(information_item['_id']),
        #               callback=self.parse_follow,
        #               dont_filter=True)
        # 获取粉丝列表
        # yield Request(url=self.base_url + '/{}/fans?page=1'.format(information_item['_id']),
        #               callback=self.parse_fans,
        #               dont_filter=True)

    def parse_tweet(self, response):
        if response.url.endswith('page=1'):
            # 如果是第1页，一次性获取后面的所有页
            all_page = re.search(r'/>&nbsp;1/(\d+)页</div>', response.text)
            if all_page:
                all_page = all_page.group(1)
                all_page = int(all_page)
                for page_num in range(2, all_page + 1):
                    page_url = response.url.replace('page=1', 'page={}'.format(page_num))
                    yield Request(page_url, self.parse_tweet, dont_filter=True, meta=response.meta)
        """
        解析本页的数据
        """
        tree_node = etree.HTML(response.body)
        tweet_nodes = tree_node.xpath('//div[@class="c" and @id]')
        # 总爬虫数加一
        for tweet_node in tweet_nodes:
            try:
                tweet_item = TweetsItem()
                self.total_scrap_num += 1
                tweet_item['dataset_id'] = self.dataset_id
                tweet_item['blogger_id'] = self.blogger_id
                tweet_item['crawl_time'] = int(time.time())
                tweet_repost_url = tweet_node.xpath('.//a[contains(text(),"转发[")]/@href')[0]
                user_tweet_id = re.search(r'/repost/(.*?)\?uid=(\d+)', tweet_repost_url)
                tweet_item['weibo_url'] = 'https://weibo.com/{}/{}'.format(user_tweet_id.group(2),
                                                                           user_tweet_id.group(1))
                tweet_item['user_id'] = user_tweet_id.group(2)
                tweet_item['_id'] = '{}_{}'.format(user_tweet_id.group(2), user_tweet_id.group(1))
                create_time_info = tweet_node.xpath('.//span[@class="ct"]/text()')[-1]
                if "来自" in create_time_info:
                    tweet_item['created_at'] = time_fix(create_time_info.split('来自')[0].strip())
                else:
                    tweet_item['created_at'] = time_fix(create_time_info.strip())

                # 设置爬虫终点,最多爬几天前的微博, 最多爬多少条
                time_now = datetime.datetime.now()
                created_time = datetime.datetime.strptime(tweet_item['created_at'], "%Y-%m-%d %H:%M")
                if (time_now - created_time).days > MAX_INTERVAL & self.total_scrap_num > MAX_SCRAP_NUM:
                    # TODO 删除这条Twitter记录
                    mongodb_operation.delete_twitter_rec(weibo_url=tweet_item['weibo_url'], dataset_id=self.dataset_id)
                    return

                # TODO 假如微博已经存在, 则删除过去微博记录以及评论记录
                mongodb_operation.delete_previous_twitter_rec(weibo_url=tweet_item['weibo_url'], current_dataset_id=self.dataset_id)
                mongodb_operation.delete_previous_comment_under_twitter(weibo_url=tweet_item['weibo_url'], current_dataset_id=self.dataset_id)

                like_num = tweet_node.xpath('.//a[contains(text(),"赞[")]/text()')[-1]
                tweet_item['like_num'] = int(re.search('\d+', like_num).group())

                repost_num = tweet_node.xpath('.//a[contains(text(),"转发[")]/text()')[-1]
                tweet_item['repost_num'] = int(re.search('\d+', repost_num).group())

                comment_num = tweet_node.xpath(
                    './/a[contains(text(),"评论[") and not(contains(text(),"原文"))]/text()')[-1]
                tweet_item['comment_num'] = int(re.search('\d+', comment_num).group())

                tweet_content_node = tweet_node.xpath('.//span[@class="ctt"]')[0]

                # 检测由没有阅读全文:
                all_content_link = tweet_content_node.xpath('.//a[text()="全文"]')
                if all_content_link:
                    all_content_url = self.base_url + all_content_link[0].xpath('./@href')[0]
                    yield Request(all_content_url, callback=self.parse_all_content, meta={'item': tweet_item},
                                  priority=1)

                else:
                    all_content = tweet_content_node.xpath('string(.)').replace('\u200b', '').strip()
                    tweet_item['content'] = all_content[0:]
                    yield tweet_item

                # 抓取该微博的评论信息
                comment_url = self.base_url + '/comment/' + tweet_item['weibo_url'].split('/')[-1] + '?page=1'
                yield Request(url=comment_url, callback=self.parse_comment, meta={'weibo_url': tweet_item['weibo_url']})

            except Exception as e:
                self.logger.error(e)

    def parse_all_content(self, response):
        # 有阅读全文的情况，获取全文
        tree_node = etree.HTML(response.body)
        tweet_item = response.meta['item']
        content_node = tree_node.xpath('//div[@id="M_"]//span[@class="ctt"]')[0]
        all_content = content_node.xpath('string(.)').replace('\u200b', '').strip()
        tweet_item['content'] = all_content[1:]
        yield tweet_item

    def parse_follow(self, response):
        """
        抓取关注列表
        """
        # 如果是第1页，一次性获取后面的所有页
        if response.url.endswith('page=1'):
            all_page = re.search(r'/>&nbsp;1/(\d+)页</div>', response.text)
            if all_page:
                all_page = all_page.group(1)
                all_page = int(all_page)
                for page_num in range(2, all_page + 1):
                    page_url = response.url.replace('page=1', 'page={}'.format(page_num))
                    yield Request(page_url, self.parse_follow, dont_filter=True, meta=response.meta)
        selector = Selector(response)
        urls = selector.xpath('//a[text()="关注他" or text()="关注她" or text()="取消关注"]/@href').extract()
        uids = re.findall('uid=(\d+)', ";".join(urls), re.S)
        ID = re.findall('(\d+)/follow', response.url)[0]
        for uid in uids:
            relationships_item = RelationshipsItem()
            relationships_item['dataset_id'] = self.dataset_id
            relationships_item['blogger_id'] = self.blogger_id
            relationships_item['crawl_time'] = int(time.time())
            relationships_item["fan_id"] = ID
            relationships_item["followed_id"] = uid
            relationships_item["_id"] = ID + '-' + uid
            yield relationships_item

    def parse_fans(self, response):
        """
        抓取粉丝列表
        """
        # 如果是第1页，一次性获取后面的所有页
        if response.url.endswith('page=1'):
            all_page = re.search(r'/>&nbsp;1/(\d+)页</div>', response.text)
            if all_page:
                all_page = all_page.group(1)
                all_page = int(all_page)
                for page_num in range(2, all_page + 1):
                    page_url = response.url.replace('page=1', 'page={}'.format(page_num))
                    yield Request(page_url, self.parse_fans, dont_filter=True, meta=response.meta)
        selector = Selector(response)
        urls = selector.xpath('//a[text()="关注他" or text()="关注她" or text()="移除"]/@href').extract()
        uids = re.findall('uid=(\d+)', ";".join(urls), re.S)
        ID = re.findall('(\d+)/fans', response.url)[0]
        for uid in uids:
            relationships_item = RelationshipsItem()
            relationships_item['dataset_id'] = self.dataset_id
            relationships_item['blogger_id'] = self.blogger_id
            relationships_item['crawl_time'] = int(time.time())
            relationships_item["fan_id"] = uid
            relationships_item["followed_id"] = ID
            relationships_item["_id"] = uid + '-' + ID
            yield relationships_item

    def parse_comment(self, response):
        # 如果是第1页，一次性获取后面的所有页
        if response.url.endswith('page=1'):
            all_page = re.search(r'/>&nbsp;1/(\d+)页</div>', response.text)
            if all_page:
                all_page = all_page.group(1)
                all_page = int(all_page)
                for page_num in range(2, all_page + 1):
                    page_url = response.url.replace('page=1', 'page={}'.format(page_num))
                    yield Request(page_url, self.parse_comment, dont_filter=True, meta=response.meta)
        selector = Selector(response)
        comment_nodes = selector.xpath('//div[@class="c" and contains(@id,"C_")]')
        for comment_node in comment_nodes:
            comment_user_url = comment_node.xpath('.//a[contains(@href,"/u/")]/@href').extract_first()
            if not comment_user_url:
                continue

            like_num_raw = comment_node.xpath('.//span[@class="cc"]').xpath('string(.)').extract_first()
            like_num = int(re.search('\d+', like_num_raw).group())
            if like_num <= MIN_LIKE:
                continue
            comment_item = CommentItem()
            comment_item['dataset_id'] = self.dataset_id
            comment_item['blogger_id'] = self.blogger_id
            comment_item['crawl_time'] = int(time.time())
            comment_item['weibo_url'] = response.meta['weibo_url']
            comment_item['comment_user_id'] = re.search(r'/u/(\d+)', comment_user_url).group(1)
            comment_item['nick_name'] = comment_node.xpath('.//a[contains(@href,"/u/")]').xpath(
                'string(.)').extract_first()
            comment_item['content'] = comment_node.xpath('.//span[@class="ctt"]').xpath('string(.)').extract_first()
            comment_item['like_num'] = like_num
            comment_item['_id'] = comment_node.xpath('./@id').extract_first()
            created_at = comment_node.xpath('.//span[@class="ct"]/text()').extract_first()
            comment_item['created_at'] = time_fix(created_at.split('\xa0')[0])
            yield comment_item


if __name__ == "__main__":
    process = CrawlerProcess(get_project_settings())
    process.crawl('weibo_spider')
    process.start()
