from wordpress_xmlrpc import Client, WordPressPost, WordPressTerm
from wordpress_xmlrpc.methods.posts import GetPosts, NewPost, DeletePost
from inscrawler.settings import WORDPRESS_ADDRESS, WORDPRESS_ADMIN_NAME, WORDPRESS_ADMIN_PASSWORD
import inscrawler.utils.scrap_info_operation as scrap_info_operation
import inscrawler.utils.picture_operation as picture_operation

def get_wordpress_client():
    return Client(WORDPRESS_ADDRESS + 'xmlrpc.php', WORDPRESS_ADMIN_NAME, WORDPRESS_ADMIN_PASSWORD)


def post_wordpress(title, content, post_status, comment_status, post_tags, categories):
    wp = get_wordpress_client()
    post = WordPressPost()
    post.title = title
    post.content = content
    post.post_status = post_status
    post.comment_status = comment_status
    post.terms_names = {
        # 'post_tag': ['test', 'firstpost'],
        # 'category': ['Introductions', 'Tests']
        'post_tag': post_tags,
        'category': categories
    }
    return wp.call(NewPost(post))


def delete_wordpress(post_id_list):
    wp = get_wordpress_client()
    total_count = 0
    for id in post_id_list:
        id = tuple(id)[0]
        wp.call(DeletePost(id))
        total_count += 1
    return total_count


def post_picture(dataset_id, pic_loacation, pic_ins_id, category):
    # TODO 删除这个图片的逻辑

    pic_bed_url = picture_operation.upload_picture(pic_loacation)

    scrap_info_operation.insert_pic_record(pic_wp_id="", pic_ins_id=pic_ins_id, dataset_id=dataset_id,
                                           category=category, pic_wp_url=pic_bed_url)
    return pic_bed_url
    # print(response)
