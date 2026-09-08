# Turkish C++ Problem Factory

Yerel ham problem dosyalarını, gelecekteki eğitim platformunun kullanabileceği sürümlü ve
doğrulanmış Türkçe C++20 paketlerine dönüştüren bağımsız pipeline. Web uygulaması veya üretim
submission servisi içermez.

**Problem paketi formatı platforma aittir ve execution engine'den bağımsızdır. Judge0 şu anda
planlanan execution backend'idir.** Judge0 değiştirilirse problem bankasının yeniden üretilmesi
gerekmez; kurulumlara göre değişen Judge0 language ID'leri paketlere yazılmaz.

## Özellikler

- OpenCode Zen Responses API adaptörü; varsayılan ücretsiz `muse-spark-1.3-contributor-free`, zorunlu `xhigh`
- Varsayılan 5 öğelik batch, bozuk öğeyi izole edip tekil yeniden deneme
- SQLite checkpoint ve kaynak hash'iyle değişmeyen tamamlanmış işleri çağrısız atlama
- 429/geçici hatalarda üstel geri çekilme; model/effort fallback yok
- JSON Schema, g++ C++20, oracle çıktıları, deterministik generator ve sample tutarlılık kontrolü
- İncelenebilir `raw`, `processing`, `completed`, `failed` dizinleri
- Gerçek kota tüketmeyen sahte adaptör ve test paketi
- İsteğe bağlı, mocklanabilir Judge0 uyumluluk smoke testi

## Kurulum

Python 3.11+, `g++` ve bir sanal ortam önerilir:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

`.env` otomatik okunmaz; tercih ettiğiniz secret yöneticisiyle veya kabukta değişkenleri export
edin. Gerçek çalıştırma için yalnızca `OPENCODE_ZEN_API_KEY` zorunludur.

## Komutlar

```bash
problem-factory validate-source examples/sources/basic.json
problem-factory process examples/sources
problem-factory status
problem-factory resume examples/sources
problem-factory retry-failed examples/sources
problem-factory validate-package artifacts/completed/iki-sayinin-toplami-<hash>
problem-factory migrate-package artifacts/completed/eski-v1-paket
```

Kota harcamadan uçtan uca örnek:

```bash
problem-factory --root work/demo process examples/sources/basic.json \
  --fake-response examples/fake-responses/basic.json
```

CLI genelindeki `--root`, alt komuttan önce yazılır. `process --batch-size N` ortam varsayılanını
tek çalıştırma için değiştirir. `resume` ve `retry-failed`, başarısız kayıtları tekrar bekleyen
duruma alır. Normal `process`, daha önce başarısız olmuş girdileri kendiliğinden harcamaz.

## Girdi ve çıktı

Girdi sözleşmesi `src/problem_factory/schemas/source-v1.json`, paket sözleşmesi
`src/problem_factory/schemas/problem-v1.json` dosyasındadır. Bir tamamlanmış paket şunları içerir:

```text
problem.json
reference.cpp
generator.py
test-strategy.md
original-source.json
tests/0000.in, tests/0000.out, ...
```

Generator yalnızca girdileri üretir. Beklenen çıktılar derlenmiş C++ referans çözümünden hesaplanır.
Kaynak ve üretim metadata'sı LLM cevabına güvenilmeden pipeline tarafından enjekte edilir.
Tam doğrulanmış örnek paket `examples/generated/` altında bulunur.

Paket şeması `1.1`, platform-owned execution ve test manifestini içerir: C++20 runtime anahtarı,
CPU/wall-time, KiB cinsinden bellek, `normalized_exact` output modu ve her `.in/.out` çifti için
görünürlük/ağırlık/kategori metadata'sı. Public `samples` problem metninin tek kaynağıdır; `tests`
alanı aynı sample'ların dosya referanslarını ve tüm hidden testlerin orchestration manifestini
tutar. Validator iki gösterimin birebir tutarlı olduğunu denetler.

Eski `1.0` paketleri LLM'e gönderilmeden migrate edilir:

```bash
problem-factory migrate-package path/to/completed-package
```

Migration önce geçici kopyayı derleyip tüm testleri doğrular, ancak başarılı olursa yalnızca
`problem.json` dosyasını atomik olarak `1.1` ile değiştirir. Kaynak hash'i ve generation metadata'sı
korunur; Muse kotası kullanılmaz. State'te `completed` görünen eski paketler normal rerunda aynı
yerel migration'dan otomatik geçirilir. Eksik veya migrate edilemeyen artifact `failed` yapılır;
yalnızca açık `retry-failed`/`resume` işlemi yeniden LLM üretimine izin verir.

## Judge0 sorumluluk sınırı

- **Problem Factory:** doğrulanmış, engine-agnostic problem paketleri üretir.
- **Platform:** kullanıcı, kurs, grup, ödev, problem bankası, submission, leaderboard, First Blood,
  scoring, test orchestration, output checking, rejudge ve analytics'i yönetir.
- **Judge0:** güvenilmeyen kodu derler/çalıştırır, execution limitlerini uygular ve ham sonucu döner.

Judge0 adaptörü assignment/scoring mantığı içermez. C++20 → Judge0 runtime/language ID eşlemesi
merkezi platform/adaptör yapılandırmasıdır.

Opsiyonel smoke testi, tamamlanmış paketi önce yerel olarak doğrular; ardından temsilî testleri
Judge0'da çalıştırıp stdout'u platformun `normalized_exact` karşılaştırmasıyla kontrol eder:

```bash
export JUDGE0_URL='http://judge0.internal:2358'
export JUDGE0_CPP20_LANGUAGE_ID='<installation-specific-id>'
export JUDGE0_AUTH_TOKEN='<optional>'
problem-factory judge0-smoke path/to/completed-package --max-tests 3
```

Judge0 yoksa normal `process`, `resume` ve `validate-package` yolları değişmeden çalışır. Otomatik
testler harici Judge0 servisi kullanmaz.

## Yapı ve devam etme garantileri

Durum `state.db` içinde kaynak adı/id anahtarı ve canonical SHA-256 ile tutulur. Tamamlanmış aynı
hash tekrar çağrılmaz. Yayınlanan paketler hash ekli, değişmez dizinlerdir. Paket dosyaları durum
`completed` olmadan önce doğrulanır ve tek dizin yeniden adlandırmasıyla yayınlanır. Yayın ile DB
commit'i arasında kesinti olursa sonraki çalıştırma tamamlanmış paketleri hash ile bulup yeniden
doğrular ve API çağırmadan kaydı onarır. API isteğinde payload tabanlı `Idempotency-Key` de gönderilir;
sunucu destekliyorsa ağ düzeyi tekrarları tekilleştirir.

429 için tüm batch `pending` kalır ve işlem durur; sonraki `resume` kaldığı yerden devam eder.
Geçici 408/409/425/429/5xx ve ağ hataları üstel beklemeyle denenir. Başka model veya daha düşük
effort seçilmez. `OPENCODE_ZEN_EFFORT=xhigh` dışında yapılandırma başlangıçta reddedilir.

## Ortam değişkenleri

- `OPENCODE_ZEN_API_KEY`: gerçek istek anahtarı
- `OPENCODE_ZEN_BASE_URL`: varsayılan `https://opencode.ai/zen/v1`
- `OPENCODE_ZEN_MODEL`: varsayılan `muse-spark-1.3-contributor-free`
- `OPENCODE_ZEN_EFFORT`: yalnızca `xhigh`
- `PROBLEM_FACTORY_BATCH_SIZE`: varsayılan `5`
- `PROBLEM_FACTORY_MAX_RETRIES`: varsayılan `4`
- `PROBLEM_FACTORY_REQUEST_TIMEOUT_SECONDS`: varsayılan `180`
- `PROBLEM_FACTORY_BACKOFF_BASE_SECONDS`: varsayılan `2`
- `PROBLEM_FACTORY_BACKOFF_MAX_SECONDS`: varsayılan `60`
- `JUDGE0_URL`: yalnızca opsiyonel smoke testi için Judge0 base URL
- `JUDGE0_AUTH_TOKEN`: gerekiyorsa `X-Auth-Token`
- `JUDGE0_CPP20_LANGUAGE_ID`: kurulumun merkezi C++20 mapping değeri; pakete yazılmaz

## Geliştirme

```bash
ruff check .
pytest -q
python -m build
```

Güvenlik kapsamı ve üretim judge için eksikler [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)
dosyasındadır. Zen endpoint/model tablosu için resmi [OpenCode Zen belgeleri](https://opencode.ai/docs/zen/)
esas alınmıştır. Gerçek entegrasyon testi bilerek çalıştırılmamıştır.
