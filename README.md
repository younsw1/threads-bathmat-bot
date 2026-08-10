# Threads 자동 발행 봇

스마트스토어 상품을 실제 구매자 후기(또는 상품 정보만)를 재료 삼아 FOMO 후크가 담긴 글로
재구성해 Claude API로 자동 생성하고 Threads에 발행하는 도구입니다. **BYOK(Bring Your Own Key)
로컬 앱**으로 동작합니다 — 본인의 Meta(Threads) 앱, Claude API 키, 네이버 커머스API 키를
직접 연동해서 쓰고, 모든 데이터는 이 컴퓨터의 로컬 SQLite(`data/app.db`)에만 저장됩니다.
중앙 서버로 전송되는 데이터는 없습니다.

두 가지 모드를 지원합니다:
- **후기리뷰 모드**: 실제 구매 후기를 인용해서 글을 씁니다. 판매자가 직접 써본 것처럼 1인칭
  경험을 지어내지 않고, "구매하신 분들이 이렇게 말씀해주시더라고요" 식으로 실제 후기만
  인용/종합합니다 (`config/persona.yaml`의 `content_source_rule`).
- **상품홍보 모드**: 아직 후기가 없는 상품용. 네이버 커머스API로 가져온 상품명·썸네일·
  셀링포인트만으로 글을 쓰고, 후기나 사용 경험을 지어내지 않습니다 (`content_source_rule_promo`).

## 구성

```
webapp/app.py           로컬 대시보드 (Flask) — 1차 진입점, 여기서 상품 관리·미리보기·발행까지 다 됩니다
src/threads_bot/         콘텐츠 생성 + Threads/네이버 API 클라이언트 + DB
  db.py                  SQLite 스키마/CRUD (설정, 상품, 후기, 발행 이력)
  naver_client.py        네이버 커머스API 클라이언트 (상품 목록 조회)
  threads_client.py      Threads API 클라이언트 (텍스트/이미지 발행, 답글, 토큰 갱신)
  content_generator.py   Claude 호출 (후기리뷰/상품홍보 모드 분기)
  schedule.py            예약 발행 시간대 계산 + queue.json 등 공용 입출력
config/persona.yaml     페르소나(톤, FOMO 후크 카테고리, 금지 표현) 정의 — 모드 공통
data/app.db              로컬 DB (git에 포함되지 않음, 최초 실행 시 자동 생성)
data/queue.json           예약 대기열 내보내기 (git 커밋 대상, GitHub Actions가 읽음)
data/queue_history.json   예약 발행 결과 로그 (GitHub Actions가 기록, git 커밋 대상)
scripts/scheduled_publish.py  GitHub Actions에서 실행되는 예약 발행 스크립트
scripts/publish.py       (부록) 상품 1개를 CLI+GitHub Actions로 자동 발행하고 싶을 때
.github/workflows/       스케줄 발행(예약 대기열) / (부록) 단일상품 자동발행 / 토큰 갱신
```

## 로컬 대시보드 실행하기

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python webapp/app.py
```

브라우저가 자동으로 `http://127.0.0.1:8765`로 열립니다. 처음 실행하면 **설정** 화면으로
이동하는데, 여기서 아래 3가지를 순서대로 연동합니다 (각 섹션에 화면 내 안내가 있습니다).

1. **Threads(Meta)**: developers.facebook.com에서 본인 앱을 만들고 "Access the Threads API"
   추가 → 테스터로 본인 계정 등록 → "사용자 토큰 생성기"로 토큰 발급 → 대시보드에 붙여넣기
   (⚠️ Redirect URI 저장이 안 되면 "앱 설정 → 기본 설정 → 앱 도메인"에 아무 도메인이나
   먼저 등록해야 합니다 — Meta 콘솔의 알려진 함정입니다)
2. **Claude API**: console.anthropic.com에서 키 발급
3. **네이버 커머스API** (상품홍보 모드용, 선택): apicenter.commerce.naver.com에서 본인 명의로
   "내 스토어 어플리케이션" 발급

각 섹션 아래 "연결 테스트" 버튼으로 바로 성공/실패를 확인할 수 있습니다. 이후 **상품 목록**
화면에서 네이버 상품을 불러오거나 수동으로 추가하고, 상품 상세에서 모드(후기리뷰/상품홍보)와
후기 데이터를 채운 뒤 **글 생성하기 → 미리보기(이미지 선택, 링크 위치) → 발행** 순서로 씁니다.

기존에 CLI로 만들어둔 `config/product.yaml`/`data/reviews.json`(욕실매트)은 최초 1회
`python scripts/migrate_to_db.py`를 실행하면 대시보드의 첫 상품으로 자동 이전됩니다.

## 예약 발행 (PC를 꺼도 랜덤한 시간대에 자동 발행)

로컬 대시보드는 켜져 있을 때만 동작하므로, "PC를 꺼둬도 알아서 올라가는" 예약 발행은
**GitHub Actions(클라우드)**가 대신합니다. 글 생성(Claude 호출)은 로컬에서 미리 끝내고
검토까지 마친 다음, 완성된 텍스트만 GitHub에 반영해두면 GitHub Actions가 정해진 시간대
안의 랜덤한 시각에 그대로 발행합니다.

1. 상품 상세 화면에서 **"예약 대기열에 추가"** → 상단 메뉴 **예약 대기열**에서 생성된 글을
   검토(필요하면 "다시 생성") → **"승인"**
2. **예약 대기열** 화면에서 발행 시간대를 켭니다 (아침 07~09시 / 점심 12~13시 / 저녁
   19~23시, 저녁이 참여도가 가장 높음 — 켠 시간대 개수만큼 하루에 발행됩니다)
3. **"승인된 항목 GitHub에 반영"** 클릭 → `data/queue.json`, `data/schedule_settings.json`이
   커밋·푸시됩니다
4. 이후 GitHub Actions(`scheduled_publish.yml`)가 켜둔 시간대마다 자동으로 깨어나서, 그
   시간대 안의 무작위 시각까지 기다렸다가 대기열에서 가장 오래된 글 1건을 그대로 발행합니다
   (이 단계는 Claude를 호출하지 않고, 로컬에서 승인한 텍스트를 그대로 씁니다)
5. 나중에 로컬 대시보드에서 **"GitHub에서 발행 결과 가져오기"**를 누르면 실제 발행 이력이
   로컬 `posts`/발행 이력 화면에 반영됩니다

**필요한 GitHub Secrets**: `THREADS_ACCESS_TOKEN`, `THREADS_USER_ID` (기존 CLI 자동화를
설정했다면 이미 등록되어 있을 수 있습니다 — 저장소 Settings → Secrets and variables →
Actions에서 확인하세요). `refresh_token.yml`이 있다면 토큰도 자동으로 계속 갱신됩니다.

---

## 부록: CLI + GitHub Actions로 상품 1개 자동화하기

여러 상품을 대시보드로 관리하는 대신, 상품 1개를 매일 정해진 시간에 자동으로 발행하고
싶다면 아래처럼 기존 CLI 방식도 그대로 쓸 수 있습니다.

### 0. 상품/후기 데이터 채우기

1. `config/product.yaml`을 열어 `name`, `smartstore_url`, `review_count`, `rating`,
   `key_selling_points`, `cta_text`를 실제 값으로 채웁니다.
2. `data/reviews.example.json`의 스키마(`id`, `text`, `rating`, `tag`)를 참고해
   `data/reviews.json`에 실제 후기를 옮겨 담습니다. 후기 원문을 그대로(또는 개인정보만
   제거하고) 넣어야, 생성기가 없는 내용을 지어내지 않고 실제 후기에 기반해 글을 씁니다.

### 1. 로컬 준비 (CLI 방식)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
```

`.env`에 `ANTHROPIC_API_KEY`만 채우면, Threads 자격증명 없이도 콘텐츠 생성만 테스트할 수 있습니다.

```bash
python scripts/publish.py --dry-run
```

페르소나 톤/후크가 마음에 들 때까지 `config/persona.yaml`을 수정하며 반복 실행해보세요.

### 2. Meta Developer 앱 만들기 (Threads API 접근)

1. https://developers.facebook.com 에 로그인 후 **My Apps → Create App** 으로 새 앱을 만듭니다.
2. 앱 대시보드에서 **Add use case → Access the Threads API** 를 추가합니다.
3. **Threads API settings**에서 Redirect URI를 등록합니다. 로컬 테스트용으로는
   `https://localhost/callback` 처럼 실제로 열리지 않아도 되는 URL을 등록해도 됩니다
   (브라우저가 리다이렉트에 실패해도 주소창의 URL만 복사하면 됩니다).
4. **Threads Testers**에 본인 Threads 계정을 테스터로 추가하고, Threads 앱/웹에서 초대를 수락합니다.
   (앱이 Meta의 App Review를 통과하기 전에는 테스터로 등록된 계정만 발행할 수 있습니다.)
5. 앱의 **App ID / App Secret**을 확인해둡니다.

### 3. 액세스 토큰 발급

`THREADS_APP_ID`, `THREADS_APP_SECRET`, 등록한 Redirect URI를 가지고 아래를 실행합니다.

```bash
python scripts/oauth_setup.py --client-id <APP_ID> --client-secret <APP_SECRET> --redirect-uri <REDIRECT_URI>
```

1. 출력된 URL을 브라우저에서 열고 본인 Threads 계정으로 로그인/동의합니다.
2. 리다이렉트된 주소(예: `https://localhost/callback?code=...`)를 그대로 복사해 콘솔에 붙여넣습니다.
3. 스크립트가 단기 토큰 → 60일짜리 장기 토큰으로 자동 교환한 뒤 `THREADS_ACCESS_TOKEN`, `THREADS_USER_ID`를 출력합니다.

### 4. GitHub 저장소 및 Secrets 설정

1. GitHub에 새 저장소를 만들고 이 폴더를 push합니다.
2. 저장소 **Settings → Secrets and variables → Actions**에서 아래 시크릿을 등록합니다.

| 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `THREADS_ACCESS_TOKEN` | 3단계에서 발급받은 장기 토큰 |
| `THREADS_USER_ID` | 3단계에서 출력된 사용자 ID |
| `GH_PAT` | 이 저장소의 Secrets를 쓸 수 있는 [Fine-grained PAT](https://github.com/settings/tokens?type=beta) (Repository permissions → Secrets: Read and write) — 토큰 자동 갱신용 |

3. **Actions** 탭에서 `Threads 자동 발행` 워크플로우를 `workflow_dispatch`로 한 번 수동 실행해
   (`dry_run=true`로 먼저) 정상 동작을 확인한 뒤, `dry_run=false`로 실제 발행을 테스트합니다.
4. 문제없으면 그대로 두면 매일 KST 09:00에 자동 발행되고, 매주 월요일 09:00에 토큰이 자동 갱신됩니다.

## 참고: Threads API 제약

- 텍스트 게시물 500자 제한
- 24시간당 최대 250건 발행 (`get_publishing_limit()`으로 사전 확인 가능)
- 장기 토큰은 60일 후 만료되며, 만료 전에만 갱신 가능 (`refresh_token.yml`이 매주 자동 갱신하므로
  워크플로우가 한 번이라도 실패한 채 60일이 지나면 `scripts/oauth_setup.py`로 재인증해야 합니다)
