SELECT 'auth_user', count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY t.id), '')) FROM auth_user t
UNION ALL SELECT 'posts_post', count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY t.id), '')) FROM posts_post t
UNION ALL SELECT 'posts_comment', count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY t.id), '')) FROM posts_comment t
UNION ALL SELECT 'posts_follow', count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY t.id), '')) FROM posts_follow t
UNION ALL SELECT 'posts_group', count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY t.id), '')) FROM posts_group t
UNION ALL SELECT 'posts_storedimage', count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY t.name), '')) FROM posts_storedimage t;
