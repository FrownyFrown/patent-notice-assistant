---
name: patent-notice
description: 공개된 특허 출원 PDF 나 TXT 로 의견제출통지서 초안을 만든다. 「처음 설정해줘」, 「이 출원 검토해줘」, 「이어서 해줘」, 청구항 구성 분해, 선행기술 후보 검색, 단락 대조, 거절이유 초안, 통지서 docx 를 말하면 쓴다.
---

# 특허 검토 초안 절차

코드로 되는 일은 `scripts/work.py` 가 한다. Codex 는 작업지를 읽고 JSON 을 쓰는 네 자리에서만 추론한다.
`PY` 는 Windows 에서 `py -3 -X utf8` (안 되면 `python -X utf8`), macOS 에서 `python3 -X utf8` 이다.
명령은 여러 번 돌려도 안전하다. 어디까지 했는지 모르면 `PY scripts/work.py status` 다음 `PY scripts/work.py next`.

## 처음 설정해줘
1. `PY scripts/work.py doctor` 를 돌리고 결과를 쉬운 말로 알린다. 동기화 폴더 경고가 나오면 폴더를 다른 곳으로 옮기라고 말한다.
2. 사용자에게 두 가지를 확인받는다. 공개된 출원만 쓴다. 넣은 글은 Codex 를 통해 OpenAI 서버로 전송되고, 소속 기관 규정 확인은 본인 책임이다.
3. 설정을 물어본다. 모르면 기본값을 쓴다. `PY scripts/work.py config max_references 4`, `config search_limit 6`, `config top_paragraphs 8`
4. 실행 전에 승인 창이 뜨는 것은 정상이라고 알린다. 승인 없이 돌리는 옵션은 권하지 않는다.
5. 예제 1회: `PY scripts/work.py new tests/example/application.txt --public-confirmed` 뒤 `next`. 예제는 지어낸 내용이다.

## 사건 하나
1. 파일은 사용자가 `input/` 에 넣는다. 공개된 출원인지 사용자가 채팅으로 확인한 뒤에만 `--public-confirmed` 를 붙인다.
   `PY scripts/work.py new "input/파일.pdf" --public-confirmed`
2. 청구항 수, 출원일, 우선일, 경고를 알리고 맞는지 묻는다. 고칠 때는 `set application-date`, `set priority-date`, `set claims-file`.
3. `next` 가 주는 작업지를 읽고, 작업지에 적힌 결과 JSON 경로에 쓰고, 작업지에 적힌 submit 을 돌린다. 이것을 끝까지 되풀이한다.
```
단계          할 일                          명령
구성 분해      청구항을 구성요소로 나눔          submit components <json>
검색          웹 검색으로 후보 번호             submit search <json>
대조          고른 단락만 읽고 판정             submit compare <json>   (문헌마다)
빈칸 검색      확인 안 된 구성만 다시 검색        submit gap <json>
판단          결론, 차이점, 이유               submit judge <json>
```
4. `fetch --pending` 은 받지 못한 공보를 다시 받는다. 네트워크 승인이 뜨면 patents.google.com 한 곳이라고 설명한다. 안 되면 사용자가 PDF 를 `input/` 에 넣고
   `fetch <번호> --file "input/문헌.pdf" --date 공개일`
   공보 글을 직접 만들지 않는다. 검색에서 본 구절을 파일로 적어 넣거나 `docs/`, `state.json` 을 손으로 쓰지 않는다. 그러면 원문 대조가 거짓이 된다. 받지 못하면 멈추고 사용자에게 PDF 를 부탁한다.
   `doctor` 는 `--offline` 없이 돌린다. 네트워크가 막혀 있으면 사용자에게 승인을 부탁한다.
5. `PY scripts/work.py verify`, `PY scripts/work.py build`. 결과는 `cases/<사건>/out/notice.docx` 와 `notice.html`.

## 단계별 기준
- 구성 분해: 글은 청구항 원문을 그대로 잘라 쓴다. 바꾸거나 줄이지 않는다. 서로 물려 작동하는 구성은 같은 group. 동의어는 한국어, 영어, 중국어를 채운다. 영어와 중국어가 비면 외국 공보에서 단락을 못 고른다.
- 검색: 청구항 1 의 핵심 구성부터. 같은 출원의 패밀리는 뺀다. 수를 채우지 않는다. 확인하지 않은 번호를 지어내지 않는다.
- 대조: 인용문은 한 단락에서 글자 그대로 옮긴다. 말줄임 금지. 문헌에 없는 기능을 본원 지식으로 채우지 않는다. 「없음」 이라고 하기 전에 낱말을 바꿔 `paragraphs` 로 한 번 더 본다.
- 판단: `references/judgement.md` 를 읽고 쓴다. 근거가 부족하면 hold, 없으면 no_reason_found. 둘 다 정상 결과다. 거절 쪽으로 맞추지 않는다. 문헌은 번호(doc_id)로 적는다. 인용발명 번호는 프로그램이 붙인다.
- 검사에 걸리면 알려 준 곳만 고쳐 다시 submit 한다. state.json 을 직접 고치지 않는다.

## 토큰 아끼기
작업지만 읽는다. 공보 전체, source.txt, state.json 을 통째로 열지 않는다. 더 필요하면 `paragraphs <doc_id> <단락번호>`. `references/` 는 그 단계에 필요할 때 한 파일만.

## 끝날 때 사용자에게 말할 것
초안이며 담당자 확인이 필요하다는 것, 거절 초안 항, 보류 항과 사유, 거절이유를 찾지 못한 항, 원문 대조 실패 건수, 빠진 문헌과 사유, 검색하지 못한 구성, 파일 위치. 논리가 깨질 지점을 한 줄씩.
결재, 발송, 파일 삭제, 저장소 공개는 하지 않는다.
