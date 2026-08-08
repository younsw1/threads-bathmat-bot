# Threads 자동 발행 봇

본인이 운영하는 스마트스토어 상품(생활/주방용품)을, 실제 구매자 후기를 재료 삼아
FOMO 후크가 담긴 글로 재구성해 Claude API로 자동 생성하고, 매일 1회 Threads에
자동 발행하는 시스템입니다. 발행은 GitHub Actions 스케줄로 트리거됩니다.

이 계정은 셀러(판매자) 본인 계정입니다. 판매자가 직접 써본 것처럼 1인칭 경험을
지어내지 않고, "구매하신 분들이 이렇게 말씀해주시더라고요" 식으로 **실제 후기만
인용/종합**하도록 설계되어 있습니다 (`config/persona.yaml`의 `content_source_rule` 참고).
없는 효능이나 허위 재고/마감 임박을 지어내는 프롬프트가 아니므로, 후기 데이터를
정확하게 채워 넣는 것이 품질의 핵심입니다.

## 구성

```
src/threads_bot/       콘텐츠 생성 + Threads API 클라이언트 + 후기/이력 관리
config/persona.yaml    페르소나(톤, FOMO 후크 카테고리, 금지 표현) 정의
config/product.yaml    홍보 대상 상품 정보 (상품명, 후기 수, 셀링포인트, CTA)
data/reviews.json      실제 구매자 후기 원본 (직접 채워야 함, data/reviews.example.json 참고)
data/post_history.json 발행 이력 (중복 회피용, 자동 기록)
scripts/publish.py     매일 실행되는 엔트리포인트
scripts/oauth_setup.py 최초 1회, Threads 인증 토큰을 발급받는 CLI
scripts/refresh_token.py  장기 토큰 자동 갱신 (주간 실행)
.github/workflows/     스케줄 발행 / 토큰 갱신 워크플로우
```

## 0. 상품/후기 데이터 채우기 (가장 먼저 할 일)

1. `config/product.yaml`을 열어 `name`, `smartstore_url`, `review_count`, `rating`,
   `key_selling_points`, `cta_text`를 실제 값으로 채웁니다.
2. `data/reviews.example.json`의 스키마(`id`, `text`, `rating`, `tag`)를 참고해
   `data/reviews.json`에 실제 후기를 옮겨 담습니다. 후기 원문을 그대로(또는 개인정보만
   제거하고) 넣어야, 생성기가 없는 내용을 지어내지 않고 실제 후기에 기반해 글을 씁니다.

## 1. 로컬 준비

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

## 2. Meta Developer 앱 만들기 (Threads API 접근)

1. https://developers.facebook.com 에 로그인 후 **My Apps → Create App** 으로 새 앱을 만듭니다.
2. 앱 대시보드에서 **Add use case → Access the Threads API** 를 추가합니다.
3. **Threads API settings**에서 Redirect URI를 등록합니다. 로컬 테스트용으로는
   `https://localhost/callback` 처럼 실제로 열리지 않아도 되는 URL을 등록해도 됩니다
   (브라우저가 리다이렉트에 실패해도 주소창의 URL만 복사하면 됩니다).
4. **Threads Testers**에 본인 Threads 계정을 테스터로 추가하고, Threads 앱/웹에서 초대를 수락합니다.
   (앱이 Meta의 App Review를 통과하기 전에는 테스터로 등록된 계정만 발행할 수 있습니다.)
5. 앱의 **App ID / App Secret**을 확인해둡니다.

## 3. 액세스 토큰 발급

`THREADS_APP_ID`, `THREADS_APP_SECRET`, 등록한 Redirect URI를 가지고 아래를 실행합니다.

```bash
python scripts/oauth_setup.py --client-id <APP_ID> --client-secret <APP_SECRET> --redirect-uri <REDIRECT_URI>
```

1. 출력된 URL을 브라우저에서 열고 본인 Threads 계정으로 로그인/동의합니다.
2. 리다이렉트된 주소(예: `https://localhost/callback?code=...`)를 그대로 복사해 콘솔에 붙여넣습니다.
3. 스크립트가 단기 토큰 → 60일짜리 장기 토큰으로 자동 교환한 뒤 `THREADS_ACCESS_TOKEN`, `THREADS_USER_ID`를 출력합니다.

## 4. GitHub 저장소 및 Secrets 설정

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
