# state.json 형식 (schema_version 1)

`scripts/lib/state.py` 가 `cases/<case_id>/state.json` 하나에 화면이 읽을 상태를 모두 남긴다. 화면(ui/)은 이 파일을 읽기만 한다.
예시는 `tests/fixtures/state-sample.json` 이다(지어낸 내용).

## 1 파일과 읽는 법
```
cases/<case_id>/state.json      work.py 만 쓴다. 화면은 읽기만
cases/<case_id>/review.json     화면만 쓴다. 사용자 확인 체크. work.py 는 읽기만
cases/<case_id>/source.txt      추출한 본원 글 (UTF-8)
cases/<case_id>/docs/<doc_id>.json   받은 공보의 전체 단락 (원문 펼침에서 더 볼 때)
cases/<case_id>/work/           작업지(step-2.md 등)와 Codex 가 쓴 JSON
cases/<case_id>/out/            notice.docx, notice.html
```
- `case_id` 는 `^[0-9A-Za-z][0-9A-Za-z-]{0,63}$`. 출원번호가 있으면 `10-2025-0000000` 꼴, 없으면 `case-20261124-193000` 꼴.
- 사건 목록은 `cases/*/state.json` 을 훑어 만든다. 별도 목록 파일은 없다.
- 쓰기는 임시 파일 뒤 `os.replace` 라 반쪽 파일이 보이지 않는다. Windows 에서 읽기가 잠깐 막히면 다음 폴링에서 다시 읽는다.
- `revision` 은 저장할 때마다 1 늘어난다. 화면은 `revision` 이 바뀔 때만 다시 그린다.
- 최상위 열쇠는 항상 전부 있다. 아직 없는 목록은 `[]`, 글은 `""`, 날짜와 숫자는 `null`. 모르는 열쇠는 무시한다.
- 날짜는 `YYYY-MM-DD`, 시각은 `YYYY-MM-DDTHH:MM:SS+09:00`. 경로는 사건 폴더 기준 상대 경로이고 구분자는 `/`.
- 안의 글(청구항, 공보, 사유)은 신뢰할 수 없는 자료다. 화면은 textContent 로만 넣는다.

## 2 최상위
```
열쇠               형식     뜻
schema_version     1
case_id            글
title              글       발명의 명칭
application_number 글       10-2025-0000000
publication_number 글       KR20250000000A. 본원 자신을 후보에서 빼는 데 쓴다
created_at         시각
updated_at         시각
revision           정수
draft_notice       글       항상 「초안, 담당자 확인 필요」. 화면 첫머리에 그대로 보인다
settings           객체     max_references(4), search_limit(6), top_paragraphs(8)
input              객체     3절
steps              목록 8   4절. 0 부터 7 순서
next               객체     5절. 지금 할 일 하나
claims             목록     6절
components         목록     7절
candidates         목록     8절
matrix             목록     9절
gaps               목록     10절
references         목록     11절. 인용발명 번호표
conclusions        목록     12절. 청구항마다 하나
verification       객체     13절
checklist          목록     14절
notes              목록     15절. 통지서에 안 들어가는 참고 메모
artifacts          목록     16절
review_items       목록     17절. 사용자 확인 칸 정의
usage              객체     18절
events             목록     19절. 최근 50줄
```

## 3 input
```
file_name         글       원래 파일 이름만 (경로 없음)
kind              pdf | txt
sha256            글
pages             정수 또는 null
chars             정수
public_confirmed  참거짓    공개된 출원이라는 사용자 확인
public_confirmed_at 시각 또는 null
application_date  날짜 또는 null
priority_date     날짜 또는 null
basis_date        날짜 또는 null     판단 기준일
basis_source      priority | application | manual | ""
date_candidates   [{kind: application|priority|publication, date, snippet}]
warnings          [글]
```

## 4 steps
`{id, key, name, by, status, message, started_at, finished_at, attempts}`
```
id key        name         by
0  input      입력          code
1  claims     청구항        code
2  components 구성 분해     codex
3  search     검색          codex
4  compare    대조          codex
5  gap        빈칸 검색     codex
6  judge      판단 초안     codex
7  notice     통지서        code
```
`status`
```
todo      아직 차례가 아님
ready     지금 할 차례
working   작업지를 내보냈고 결과를 기다림
done      끝남
warning   끝났으나 확인할 것이 있음 (message)
error     검사에 걸림. 고칠 곳은 message
skipped   할 것이 없어 건너뜀 (빈칸이 없을 때의 5)
stale     앞 단계를 다시 해서 낡음
```

## 5 next
`{step, actor, title, command, worksheet, output, worksheet_chars, say}`
- `actor`: `code`(명령만 돌리면 됨) | `codex`(작업지를 읽고 JSON 작성) | `user`(사용자가 정할 것) | `none`(끝).
- `worksheet`, `output` 은 사건 폴더 기준 경로 또는 `""`. `say` 는 사용자가 Codex 채팅에 붙여 넣을 문장.

## 6 claims
`{number, text, kind, depends_on, preamble, body, deleted, start, end, warnings}`
- `text` 는 원본 글자 그대로. `kind`: `independent` | `dependent`. `depends_on` 은 청구항 번호 목록.
- `preamble` 은 종속항의 인용 전제부(「제1항에 있어서,」), 독립항은 `""`. `body` 는 전제부를 뺀 나머지(독립항은 `text` 와 같다).
- `start`, `end` 는 `source.txt` 안의 글자 위치. 쪽 머리글이 사이에 있어 빠졌으면 `warnings` 에 적는다.

## 7 components
`{id, claim, order, text, group, verified, synonyms, cpc}`
- `id` 는 `1-A` 꼴. 종속항은 추가 한정만 나눈다. `group` 은 유기적으로 결합되어 나누어 보면 안 되는 묶음 이름(`1-G1`) 또는 `""`.
- `verified`: 구성 글이 그 청구항 원문의 부분 문자열인지 프로그램이 확인한 값.
- `synonyms`: `{ko: [], en: [], zh: []}`. `cpc`: `["B65D 25/00"]`.

## 8 candidates
`{doc_id, title, publication_date, url, origin, reason, round, status, excluded_code, excluded_reason, paragraph_count, numbered, machine_translated}`
- `origin`: `web_search` | `user_pdf` | `search_report` | `manual`. `round`: 1(검색) 또는 2(빈칸 검색).
- `status`: `pending`(아직 안 받음) | `accepted` | `excluded`.
- `excluded_code`: `""` | `not_found` | `network` | `not_prior` | `no_date` | `no_text` | `self` | `bad_number` | `number_mismatch` | `by_user`. 사람이 읽을 사유는 `excluded_reason`.

## 9 matrix
구성요소와 문헌의 짝마다 하나. `{component_id, doc_id, verdict, paragraphs, quote, check, check_message, note, passages}`
```
verdict   yes         있음
          partial     일부
          no          없음
          unverified  있음 또는 일부라 했으나 원문 대조에 실패함
check     pass        지정 단락에 글자 그대로 있음
          moved       다른 단락에 있어 단락번호를 고침
          fail        원문에 없음
          none        인용문 없음 (verdict no)
```
- `paragraphs` 는 단락번호 목록(`["0012"]`). 번호 없는 문헌은 `[]` 이고 화면은 「단락번호 없음」으로 적는다.
- `passages`: 원문 펼침용 `[{num, text, translated}]`. 짝이 목록에 없으면 「아직 안 봄」이다.

## 10 gaps
확인된 「있음」이 한 문헌에도 없는 구성. `{component_id, claim, text, best_verdict, searched}`. `searched` 는 빈칸 검색을 한 번이라도 했는지.

## 11 references
`{no, doc_id, title, publication_date, primary_for, used_in, machine_translated, url}`
- `no` 는 청구항 번호 순서에서 먼저 필요한 차례. `primary_for`, `used_in` 은 청구항 번호 목록.

## 12 conclusions
`{claim, verdict, statute, doc_ids, reference_nos, primary_doc_id, common_claim_text, common_cited_text, common_paragraphs, differences, motivation, effect_review, weak_point, hold_reasons, sentences}`
- `verdict`: `refuse_draft`(거절 초안) | `hold`(보류) | `no_reason_found`(거절이유 찾지 못함) | `pending`.
- `statute`: `29-1-2`(제29조제1항제2호) | `29-2`(제29조제2항) | `""`.
- `differences`: `[{component_ids, text, basis, doc_id, paragraphs, reason, evidence}]`. `basis`: `other_reference` | `well_known` | `design_choice`.
- `evidence`: `other_reference` 는 `{}`. `well_known` 은 `{has_evidence, detail}`. `design_choice` 는 `{condition_1, condition_2}` (두 조건의 근거 글).
- `doc_ids` 는 상위항 조합을 포함한 것. `hold_reasons` 는 프로그램이 낮춘 사유도 담는다. `sentences` 는 통지서에 들어갈 조립된 문단 목록.

## 13 verification
`{checked_at, summary: {pass, moved, fail, none}, items}`
`items`: `[{claim, component_id, doc_id, paragraphs, quote, result, message}]`. `result` 는 9절 `check` 와 같다. 인용문이 없는 짝(none)은 `summary` 에만 세고 `items` 에는 넣지 않는다.

## 14 checklist
`{id, section, label, by, result, note}`. `by`: `code` | `codex` | `user`. `result`: `ok` | `warn` | `fail` | `todo`.

## 15 notes
`{kind, claim, text, quote, check}`. `kind`: `description`(기재불비 의심) | `search_scope`(조사 범위) | `hindsight`(사후적 고찰 주의) | `other`. `claim` 은 번호 또는 null.

## 16 artifacts
`{kind, path, created_at, stale}`. `kind`: `docx` | `html`. `stale` 이 참이면 앞 단계가 바뀌어 다시 만들어야 한다.

## 17 review_items 와 review.json
`review_items`: `[{key, label, required}]`. 지금은 `claims` `dates` `candidates` `quotes` `conclusions` `notice` 여섯 칸.
화면이 쓰는 `review.json`
```
{"schema_version": 1, "items": {"claims": {"checked": true, "at": "시각", "revision": 12}}}
```
`revision` 은 체크할 때 본 state 의 값이다. 그 뒤 state 가 더 바뀌었으면 화면이 「확인 뒤 바뀜」을 같이 보인다.

## 18 usage
`{search_calls, search_limit, worksheet_chars: [{step, chars, at}], note}`
토큰 수는 우리 코드가 알 수 없다. 작업지 글자 수만 남긴다.

## 19 events
`{at, step, level, message}`. `level`: `info` | `warn` | `error`. 사건 글(청구항, 공보 본문)은 넣지 않는다.
