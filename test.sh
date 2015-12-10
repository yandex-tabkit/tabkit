#!/bin/bash

set -e
set -o pipefail

testdir=$(mktemp -d)

trap "echo 'Test failed.'" ERR
trap "rm -rf $testdir" EXIT

# запускаем pylint на всех питонячьих файлах
(echo 'run pylint on tabkit executables'; find . \
    -maxdepth 1 \
    -type f \
    -exec awk '{if(/^#!.*python/){exit(0)}else{exit(1)}}' '{}' ';' \
    -print \
| xargs -r pylint --errors-only 2>&1 ) \
| fgrep -v 'Exception RuntimeError:' >&2

(echo 'run pylint on tabkit library'; find tabkit \
    -maxdepth 1 \
    -type f \
    -name '*.py' \
    -print \
| xargs -r pylint --errors-only 2>&1 ) \
| fgrep -v 'Exception RuntimeError:' >&2

python -m doctest tabkit/awk.py
python -m doctest tabkit/awk_grp.py
python -m doctest tabkit/header.py
python -m doctest tabkit/datasrc.py
python -m doctest tabkit/pyparser.py
python -m doctest tabkit/safe_popen.py
PYTHONPATH=. python tabkit/test_tregroup.py

./_compile_tools.py "$testdir"
cd "$testdir"
PATH=.:"$PATH"
[ "$(type -p tcat)" == "./tcat" ] || (echo "failed to set PATH var" && exit 1)

## ТЕСТ tmap_awk #############

diff -ub - <(echo|tmap_awk -H"# a #ORDER: a" -o 'a;c=a') <<-TEST_END
# a c #ORDER: a 

TEST_END

# комментарии в фильтрах
diff -ub - <(echo -e "# a b\n1\t1\n1\t2" | tmap_awk -f 'a==1 # aaa' -f 'b==1 # bbb') <<-TEST_END
# a b
1       1
TEST_END


## ТЕСТ tmap_awk функций is_in_file и map_from_file #############
diff --label "LINE ${LINENO}: tmap_awk: is_in_file and map_from_file" -ub - <(echo -e '# x\n1\n2\n3 4 5' \
    | ./tmap_awk \
    -o '_compound_key=gensub(" " , "\t", "G", x)' \
    -o '_piped_file1="'<(echo -e '1\n2\tval2\n3\t4\t5\n6')'"' \
    -o '_piped_file2="'<(echo -e '1\n2\tval2\n3\t4\t5')'"' \
    -o 'x' \
    -o 'x1=is_in_file(_piped_file1, x)' \
    -o 'x1_compound=is_in_file(_piped_file1, _compound_key)' \
    -o 'x2=map_from_file(_piped_file2, x, "None")' \
    -o 'x2_compound=map_from_file(_piped_file2, _compound_key, "None_compaund")' \
) <<-TEST_END
# x     x1      x1_compound     x2      x2_compound
1       1       1
2       0       0       val2    val2
3 4 5   0       1       None    None_compaund
TEST_END


## ТЕСТ tgrp_awk #############

function test_map {
    tmap_awk --print-cmd -H"# a b c" -A mawk -f 'a==1' -o 'x=b+1; y=a if c else b' 2>&1|head -n 1
}

diff -u - <(test_map) <<-TEST_END
LC_ALL=C mawk  -F $'\t' 'BEGIN{OFS="\t";}{if((\$1 == 1)){print((\$2 + 1),(\$3?\$1:\$2));}}'
TEST_END

diff -ub - <(echo -en "\
# url
http://ya.ru
проверка.рф
https://mail.ru?qwe
https://rambler.ru:8080/asd
" | tmap_awk --pytrace -o 'dom=domain(url);netloc=netlocator(url)') <<-TEST_END
# dom   netloc
ya.ru   ya.ru
проверка.рф проверка.рф
mail.ru mail.ru
rambler.ru  rambler.ru:8080
TEST_END

diff -ub - <(
    echo -e "# a:str b:str c\n1\t2\t3" \
    | tmap_awk -o 'x=join("-", a, b); y=unjoin("-", x, 0); z="(",a,b,c,")"'
) <<-"TEST_END"
# x:str y z
1-2   1   (123)
TEST_END

diff -ub - <(
    echo -e "# a\n1==2==3" \
    | tmap_awk -o 'x=unjoin("==", a, 0); y=unjoin("==", a, 1)'
) <<-TEST_END
# x y
1   2
TEST_END


## ТЕСТ tgrp_awk #############

function test_grp {
    tgrp_awk --print-cmd -H"# a b c" -A gawk -g 'a=a' -o 'x=sum(b); y=avg(c)' 2>&1|head -n 1
}

diff -u - <(test_grp) <<-TEST_END
LC_ALL=C gawk  -F $'\t' 'BEGIN{OFS="\t";__grp_1 = 0;__grp_0 = 0;__grp_2 = 0;__print_last = 0;}{__row_key0 = (\$1  "");if(NR==1){__key0 = __row_key0;}else{if(__key0!=__row_key0){print(__key0,__grp_0,(__grp_1 / __grp_2));__key0 = __row_key0;__grp_1 = 0;__grp_0 = 0;__grp_2 = 0;}}__grp_1 += \$3;__grp_0 += \$2;__grp_2 += 1;}END{if(NR!=0 || __print_last==1){print(__key0,__grp_0,(__grp_1 / __grp_2));}}'
TEST_END

diff -ub - <(echo "# a"|tgrp_awk -g 'a=a' -o 'x=sum(a)') <<-TEST_END
# a x:float
TEST_END

diff -ub - <(echo "# a"|tgrp_awk -o 'x=sum(a)') <<-TEST_END
# x:float
0
TEST_END

diff -ub - <(
    echo -e "# k a:str b:int c:float d\nk\t1\t2\t0.5\ttest\nk\t10\t20\t5\ttest2" \
    | tgrp_awk -G "k" -o "A=sum(a);B=max(b);C=ifmin(c,d)"
) <<-TEST_END
# k A:float B:int C
k 11 20 test
TEST_END

# опция --expose-groups
diff -ub - <(
    echo -e "# k a:str b:int c:float d\nk\t1\t2\t0.5\ttest\nk\t10\t20\t5\ttest2" \
    | tgrp_awk -e -G "k" -o "A=sum(a);B=max(b);C=ifmin(c,d)"
) <<-TEST_END
# k A:float B:int C
k  1  2 test
k 11 20 test
TEST_END

# -G, обработка строк, похожих на числа, сортировка
diff -ub - <(
    echo -e '0\t0\t0\t1\n0\t0\t0\t3\n0\t0\t0\t4\n0\t0\t00\t4' \
    | tsrt -H '# a b c d' -k a -k b:desc -k c:num -k d:num \
    | tgrp_awk -G 'a;b;c;d=d%2' -o 'cnt=cnt()'
) <<-TEST_END
# a     b       c       d       cnt:int #ORDER: a       b:desc  c:num
0       0       0       1       2
0       0       0       0       1
0       0       00      0       1
TEST_END

# вложенность функций в grp контексте - RowExprSubscript
diff -ub - <(
    echo "a b c" \
    | tgrp_awk -H "# x" -o 'y=sum(unjoin_count(" ", x))'
) <<-TEST_END
# y:float
3
TEST_END

# вложенность функций в grp контексте - RowExprSubscript
diff -ub - <(
    echo -e '1 2\n3  4' \
    | tgrp_awk -H '# x' -o 'z=sum(unjoin(" ", x, unjoin_count("-", x)))'
) <<-TEST_END
# z:float
6
TEST_END

# вложенность функций в grp контексте - RowExprSideEffectVar
diff -ub - <(
    echo -e '1\t2\n3\t4' \
    | tgrp_awk -H '# x y' -o 'z=sum(10*shell("echo 1")+x*y)'
) <<-TEST_END
# z:float
24
TEST_END

# строковое сравнение полей
diff -ub - <(
    echo -e '# a b\n1\t5\n1\t05' \
    | tgrp_awk --expose-groups -G 'a' \
        -o 'c = last(b) if last(b) != first(b) else 0.01'
) <<-TEST_END
# a c
1   0.01
1   0.01
TEST_END

## ТЕСТ tsrt #############

diff -ub - <(echo "# a"|tsrt -k a:desc:num --batch-size=8 --print-cmd) <<-TEST_END
LC_ALL=C sort -t$'\t' -k1,1nr --batch-size=8
TEST_END

# опция --stream-check
diff -ub - <(echo -e "# x\n1\n2\n03" | (tsrt -k x:num --stream-check && echo TEST_PASSED)) <<-TEST_END
# x #ORDER: x:num
1
2
03
TEST_PASSED
TEST_END

diff -ub - <(echo -e "# x\n1\n2\n03" | (./tsrt -k x --stream-check 2>&1 1>/dev/null || echo 'sort: TEST_PASSED') | grep 'sort:') <<-TEST_END
sort: -:3: disorder: 03
sort: TEST_PASSED
TEST_END

## ТЕСТ tcut #############

diff -ub - <(tcut -f b,d --print-cmd <(echo "# a b c d") <(echo "# b d") <(echo "# b d")) <<-TEST_END
cut -f 2,4 /dev/fd/63
cut -f 1,2 /dev/fd/62 /dev/fd/61
TEST_END

diff -ub - <(tcut -r a,c --print-cmd <(echo "# a b c d") <(echo "# b d") <(echo "# b d")) <<-TEST_END
cut -f 2,4 /dev/fd/63
cut -f 1,2 /dev/fd/62 /dev/fd/61
TEST_END

diff -ub - <(
    echo -e "# a:str b:int c:float d\n1\t2\t0.5\ttest" \
    | tmap_awk -a -o "A=c/b;B=int(c);C=b+b;D=a<d;"
) <<-TEST_END
# a:str b:int c:float d A:float B:int C:int D:bool
1 2 0.5 test 0.25 0 4 1
TEST_END

## ТЕСТ tjoin #############

# tjoin с составным ключом
diff -ub - <(
    ./tjoin -j a,b \
        <(echo -e "# x b y a:int #ORDER: a b x:num:desc \n1\tb\t3\ta\n2\tb\t3\ta") \
        <(echo -e "# a b z       #ORDER: a b z          \na\tb\t5\na\tb\t6")
) <<-TEST_END
# x b   y   a:int   z #ORDER: a b   x:desc:num  z
1      b       3       a       5
1      b       3       a       6
2      b       3       a       5
2      b       3       a       6
TEST_END

# tjoin с неоднозначным выводом составного ключа 1
diff -ub - <(
    ./tjoin -j a,b,c,d -o x,c,b,y,a,d \
        <(echo -e "# a b c d x #ORDER: a b c d\n1\t2\t3\t4\tX") \
        <(echo -e "# a b c d y #ORDER: a b c d\n1\t2\t3\t4\tY")
) <<-TEST_END
# x c b y a d #ORDER: a b c d
X 3 2 Y 1 4
TEST_END

# tjoin с обратным выводом составного ключа 2
diff -ub - <(
    ./tjoin -j a,b,c,d -o d,c,b,a \
        <(echo -e "# a b c d #ORDER: a b c d\n1\t2\t3\t4") \
        <(echo -e "# a b c d #ORDER: a b c d\n1\t2\t3\t4")
) <<-TEST_END
# d c b a #ORDER: a b c d
4 3 2 1
TEST_END

# tjoin -a с составным ключом
diff -ub - <(
    ./tjoin -j x,y -a 1 -a 2 \
        <(echo $'#x y #ORDER: x, y\n1\t10\n2\t20') \
        <(echo $'#x y #ORDER: x, y\n2\t20\n3\t30')
) <<-TEST_END
# x y #ORDER: x y
1   10
2   20
3   30
TEST_END

# tjoin -c с составным ключом
diff -ub - <(
    ./tjoin -j x,y -c 2 \
        <(echo $'#x y z #ORDER: x, y\n2\t20\tz1') \
        <(echo $'#x y z #ORDER: x, y\n2\t20\tz2')
) <<-TEST_END
# x y z #ORDER: x y
2   20  z2
TEST_END

# шаблонное переименование
diff -ub - <(
    ./tjoin -1 a -2 a2  -r "2.*=*2" \
        <(echo -e "# x b y a:int #ORDER: a x:num:desc \n1\tb\t3\ta") \
        <(echo -e "# a b z       #ORDER: a b z        \na\tb\t5") \
) <<-TEST_END
# x b   y   a:int   b2  z2 #ORDER: a    x:desc:num  b2  z2
1   b   3   a   b   5
TEST_END

# шаблонное переименование с составным ключом
diff -ub - <(
    ./tjoin -1 a,b -2 a2,b2  -r "2.*=*2" \
        <(echo -e "# x b y a:int #ORDER: a b x:num:desc \n1\tb\t3\ta") \
        <(echo -e "# a b z       #ORDER: a b z        \na\tb\t5") \
) <<-TEST_END
# x b   y   a:int   z2 #ORDER: a    b   x:desc:num  z2
1   b   3   a   5
TEST_END

# ошибка при шаблонном переименовании
diff -ub - <(
    ./tjoin -1 a -2 a2  -r "2.*=*2" \
        <(echo -e "# x b2 y a:int #ORDER: a x:num:desc \n1\tb\t3\ta") \
        <(echo -e "# a b z       #ORDER: a b z        \na\tb\t5") \
    2>&1
) <<-TEST_END
./tjoin: Exception: Field name 'b2' presents in both files, use -r/-o/-c option to resolve conflict
TEST_END

## ТЕСТ tproject #############

diff -ub - <(
    echo -en "\
# date  premium stable  c   s
1\tpr\tU\t111\t111111
1\tn\tU\t222\t222222
1\tn\tS\t333\t333333
2\tpr\tU\t444\t444444
2\tpr\tS\t555\t555555
" | ./tproject -d- -G date -P premium,stable --format '{0}_{1.value}_{2.value}'
) <<EOF
# date  c_pr_U  c_n_U   c_n_S   c_pr_S  s_pr_U  s_n_U   s_n_S   s_pr_S
1   111 222 333 -   111111  222222  333333  -
2   444 -   -   555 444444  -   -   555555
EOF

## ТЕСТ tparallel -y #############
diff --label "LINE ${LINENO}: tparallel -y" -ub - <(echo -e '---\na = 1\n---\nb = 2' | tparallel -N -y cat | sort) <<-TEST_END
---
---
a = 1
b = 2
TEST_END

## ТЕСТ tregroup #############
diff -ub - <(
    echo -en "\
# A B C
f\tfoo\t100
f\tbar\t3
f\tfoo\t5
b\tbar\t1
b\tbar\t-5
" | ./tregroup -K 'A' -k 'B' -s 'C:num' --lru
) <<EOF
# A  B   C
f    bar 3
f    foo 5
f    foo 100
b    bar -5
b    bar 1
EOF

## ТЕСТ twiki ############
diff -ub - <(
    echo -en "\
# A B C
foo\t11.1111\t1.2.3
2.22222\tbar\t.2.
" | ./twiki
) <<EOF
%%(csv delimiter=; head=1)
A;B;C
foo;11.1111;1.2.3
2.22222;bar;.2.
%%
EOF

diff -ub - <(
    echo -en "\
# A B C
foo\t11.1111\t1.2.3
2.22222\tbar\t.2.
" | ./twiki -d 2
) <<EOF
%%(csv delimiter=; head=1)
A;B;C
foo;11.11;1.2.3
2.22;bar;.2.
%%
EOF

## ТЕСТ tpretty ##########
diff -ub - <(
    echo -en "\
# A B C
foo\t11.1111\t1.2.3
2.22222\tbar\t.2.
" | ./tpretty
) <<EOF
A       | B       | C
--------|---------|-------
foo     | 11.1111 | 1.2.3
2.22222 | bar     | .2.
EOF

diff -ub - <(
    echo -en "\
# A B C
foo\t11.1111\t1.2.3
2.22222\tbar\t.2.
" | ./tpretty -d 2
) <<EOF
A    | B     | C
-----|-------|-------
foo  | 11.11 | 1.2.3
2.22 | bar   | .2.
EOF

## ТЕСТ thash ##########
diff -ub - <(
	echo -en "\
# A B C
foo\t12345\t1a2b3c
" | ./thash -o 'a_bsmd5=bs_md5(A);c_crc32=crc32(C);b_sha1=sha1(B)'
) <<EOF
# A     B       C       a_bsmd5:str     c_crc32:str     b_sha1:str
foo     12345   1a2b3c  9225162609816403348     -350793248      8cb2237d0679ca88db6464eac60da96345513964
EOF