UPDATE accounts AS a
SET platform = REPLACE(a.platform, '_CARDS', ''),
    platform_id = p.id
FROM platforms AS p
WHERE a.platform IN ('UOB_CARDS', 'DBS_CARDS')
  AND p.code = REPLACE(a.platform, '_CARDS', '');

DELETE FROM platforms
WHERE code IN ('UOB_CARDS', 'DBS_CARDS');
