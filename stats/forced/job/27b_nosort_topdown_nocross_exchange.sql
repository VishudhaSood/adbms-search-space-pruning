LOAD 'pg_lab';
SET enable_indexscan = off; SET enable_indexonlyscan = off; SET enable_bitmapscan = off;
SET max_parallel_workers_per_gather = 0; SET geqo = off; SET jit = off;
/*=pg_lab= Config(plan_mode=full; exec_mode=sequential)
   JoinOrder((mi ((((cc (cn (mc (lt (t (ml (mk k))))))) cct1) cct2) ct)))  HashJoin(mk k)  HashJoin(ml mk k)  HashJoin(t ml mk k)  HashJoin(lt t ml mk k)  HashJoin(mc lt t ml mk k)  HashJoin(cn mc lt t ml mk k)  HashJoin(cc cn mc lt t ml mk k)  HashJoin(cc cn mc lt t ml mk k cct1)  HashJoin(cc cn mc lt t ml mk k cct1 cct2)  HashJoin(cc cn mc lt t ml mk k cct1 cct2 ct)  HashJoin(mi cc cn mc lt t ml mk k cct1 cct2 ct)
   SeqScan(cc) SeqScan(cct1) SeqScan(cct2) SeqScan(cn) SeqScan(ct) SeqScan(k) SeqScan(lt) SeqScan(mc) SeqScan(mi) SeqScan(mk) SeqScan(ml) SeqScan(t) */
SELECT MIN(cn.name) AS producing_company,
       MIN(lt.link) AS link_type,
       MIN(t.title) AS complete_western_sequel
FROM complete_cast AS cc,
     comp_cast_type AS cct1,
     comp_cast_type AS cct2,
     company_name AS cn,
     company_type AS ct,
     keyword AS k,
     link_type AS lt,
     movie_companies AS mc,
     movie_info AS mi,
     movie_keyword AS mk,
     movie_link AS ml,
     title AS t
WHERE cct1.kind IN ('cast',
                    'crew')
  AND cct2.kind = 'complete'
  AND cn.country_code !='[pl]'
  AND (cn.name LIKE '%Film%'
       OR cn.name LIKE '%Warner%')
  AND ct.kind ='production companies'
  AND k.keyword ='sequel'
  AND lt.link LIKE '%follow%'
  AND mc.note IS NULL
  AND mi.info IN ('Sweden',
                  'Germany',
                  'Swedish',
                  'German')
  AND t.production_year = 1998
  AND lt.id = ml.link_type_id
  AND ml.movie_id = t.id
  AND t.id = mk.movie_id
  AND mk.keyword_id = k.id
  AND t.id = mc.movie_id
  AND mc.company_type_id = ct.id
  AND mc.company_id = cn.id
  AND mi.movie_id = t.id
  AND t.id = cc.movie_id
  AND cct1.id = cc.subject_id
  AND cct2.id = cc.status_id
  AND ml.movie_id = mk.movie_id
  AND ml.movie_id = mc.movie_id
  AND mk.movie_id = mc.movie_id
  AND ml.movie_id = mi.movie_id
  AND mk.movie_id = mi.movie_id
  AND mc.movie_id = mi.movie_id
  AND ml.movie_id = cc.movie_id
  AND mk.movie_id = cc.movie_id
  AND mc.movie_id = cc.movie_id
  AND mi.movie_id = cc.movie_id;
