
-- 云市应用官方认证及安装量排序增加字段
ALTER TABLE `rainbond_center_app` ADD COLUMN `install_number` INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE `rainbond_center_app` ADD COLUMN `is_official` bool DEFAULT false NOT NULL;


-- 云帮应用添加server_type字段
ALTER TABLE `tenant_service` ADD COLUMN `server_type` varchar(5) default 'git';
ALTER TABLE `tenant_service_delete` ADD COLUMN `server_type` varchar(5) default 'git';

-- 添加用户申请加入团队表
CREATE TABLE applicants
(
    id int PRIMARY KEY NOT NULL AUTO_INCREMENT,
    user_id int NOT NULL,
    user_name varchar(20) NOT NULL,
    team_id int NOT NULL,
    team_name varchar(20) NOT NULL,
    apply_time datetime NOT NULL,
    team_alias varchar(30) NOT NULL,
    is_pass tinyint DEFAULT FALSE  NOT NULL
);
CREATE UNIQUE INDEX applicants_id_uindex ON applicants (id);

