# tabkit

Python wrappers around coreutils (cat, join, sort, cut, awk, pv) to support tab-separated files with headers.
Headers describe field names, types and data ordering.

------------------

## Install:

```bash
python2 setup.py install --prefix=~/.local
# make sure that installation bin location in $PATH
# or export PATH="$HOME/.local/bin:$PATH"
```

------------------

## Examples:

```bash
$ cat file 
# shows clicks page_id date
300	1	100	20140707
1543	17	11205	20140707
100500	777	31105	20140707
287	3	100	20140708
1333	22	11205	20140708
100555	666	31105	20140708
```

### tmap_awk
```bash
$ cat file | tmap_awk -o date -o page_id -o 'ctr=clicks/shows'
# date	page_id	ctr
20140707	100	0.00333333
20140707	11205	0.0110175
20140707	31105	0.00773134
20140708	100	0.010453
20140708	11205	0.0165041
20140708	31105	0.00662324

$ cat file | tmap_awk -f 'page_id>1000'
# shows	clicks	page_id	date
1543	17	11205	20140707
100500	777	31105	20140707
1333	22	11205	20140708
100555	666	31105	20140708

tmap_awk --help
```

### tsrt
```bash
$ cat file | tsrt -k page_id
# shows	clicks	page_id	date #ORDER: page_id
287	3	100	20140708
300	1	100	20140707
1333	22	11205	20140708
1543	17	11205	20140707
100500	777	31105	20140707
100555	666	31105	20140708

$ cat file | tsrt -k shows:desc:num
# shows	clicks	page_id	date #ORDER: shows:desc:num
100555	666	31105	20140708
100500	777	31105	20140707
1543	17	11205	20140707
1333	22	11205	20140708
300	1	100	20140707
287	3	100	20140708
```

### tgrp_awk
```bash
$ cat file | tsrt -k page_id | tgrp_awk -G page_id -o 'clicks=sum(clicks)' -o 'shows=sum(shows)'
# page_id	clicks:float	shows:float #ORDER: page_id
100	4	587
11205	39	2876
31105	1443	201055
```

### tjoin
```bash
$ cat file3 
# page_id  rank
11205	7
100	10

$ tjoin -j page_id \
    <(cat file3 | tsrt -k page_id) \
    <(cat file | tsrt -k page_id)
# page_id	rank	shows	clicks	date #ORDER: page_id
100	10	287	3	20140708
100	10	300	1	20140707
11205	7	1333	22	20140708
11205	7	1543	17	20140707
```


### twiki
```bash
$ cat file | twiki 
%%
%%(csv delimiter=; head=1)
shows;clicks;page_id;date
300;1;100;20140707
1543;17;11205;20140707
100500;777;31105;20140707
287;3;100;20140708
1333;22;11205;20140708
100555;666;31105;20140708
```

### tpretty
```bash
$ cat file | tpretty 
shows   | clicks | page_id | date    
--------|--------|---------|----------
300     | 1      | 100     | 20140707
1543    | 17     | 11205   | 20140707
100500  | 777    | 31105   | 20140707
287     | 3      | 100     | 20140708
1333    | 22     | 11205   | 20140708
100555  | 666    | 31105   | 20140708
```

# tyaml_parser
```yaml
---
addtime: 1401831173
classes:
    auto:
        - 9000300
        - 9000008
    auto_raw:
        - 9000300
        - 9000008
    catalog: []
    catalog_raw: []
    catalogia:
        - 200001789
    tragic: []
doc_charset: 'utf-8'
hits: 1
lang: rus
pageid: 64532
status: 200
url: 'http://www.opengost.ru/download/8261/GOST_21804-94_Ustroystva_zapornye_ballonov_dlya_szhizhennyh_uglevodorodnyh_gazov_na_davlenie_do_1_6_MPa_TU.html'
---
addtime: 1401831175
classes:
    auto:
        - 9000333
        - 9000007
    auto_raw:
        - 9000333
        - 9000007
    catalog: []
    catalog_raw: []
    catalogia:
        - 200001780
        - 200001789
    tragic: []
doc_charset: 'utf-8'
hits: 1
lang: rus
pageid: 64532
status: 200
url: 'http://www.opengost.ru/download/8645/GOST_3859-83_Golovki_revol_vernye_dlya_tokarno-revol_vernyh_stankov_Tipy_i_osnovnye_razmery.html'
```

```bash
$ cat file2 | tyaml_parser -o 'pageid=r["pageid"]' -o 'catalogia=",".join(map(str, r["classes"].get("catalogia", [])))'
# pageid catalogia
64532	200001789
64532	200001780,200001789
```
