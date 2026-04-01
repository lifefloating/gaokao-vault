INSERT INTO subject_categories (name, category_type) VALUES
('文科', 'traditional'),
('理科', 'traditional'),
('物理类', 'new'),
('历史类', 'new'),
('综合改革', 'new')
ON CONFLICT (name) DO NOTHING;
