INSERT INTO subject_categories (name, category_type) VALUES
-- traditional
('文科', 'traditional'),
('理科', 'traditional'),
-- new gaokao
('物理类', 'new'),
('历史类', 'new'),
('综合改革', 'new'),
('综合', 'new'),
-- common special
('艺术类', 'special'),
('体育类', 'special'),
('艺术文', 'special'),
('艺术理', 'special'),
('体育文', 'special'),
('体育理', 'special'),
-- Inner Mongolia bilingual
('蒙授理科', 'special'),
('蒙授文科', 'special'),
('汉授美术', 'special'),
('汉授音乐', 'special'),
('汉授编导', 'special'),
('汉授其他艺术', 'special'),
('汉授体育', 'special'),
('蒙授其他艺术', 'special'),
('蒙授体育', 'special'),
('蒙授音乐', 'special'),
('蒙授美术', 'special'),
-- xue-kao
('学考理', 'special'),
('学考文', 'special'),
-- vocational / dukou
('医学类', 'special'),
('计算机类', 'special'),
('农学类', 'special'),
('财会类', 'special'),
('化工类', 'special'),
('美工设计类', 'special'),
('牧医类', 'special'),
('采矿类', 'special'),
('幼师类', 'special'),
('蒙牧医类', 'special'),
('旅游类', 'special'),
('机电类', 'special'),
('建筑类', 'special'),
('汽驾类', 'special'),
-- art sub-categories
('广播电视编导类', 'special'),
('舞蹈类', 'special'),
('美术类', 'special'),
('音乐类', 'special'),
('书法类', 'special'),
('农林类', 'special'),
('烹饪类', 'special'),
('畜牧兽医类', 'special'),
-- the exact category from the bug log
('单独考试招生', 'special')
ON CONFLICT (name) DO NOTHING;
