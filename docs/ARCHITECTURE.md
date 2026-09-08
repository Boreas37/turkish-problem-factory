# Execution engine sınırı

Canonical `problem.json` ve test dosyaları platformun veri modelidir. Paket hiçbir Judge0
submission token'ı, language ID'si, host adı veya kurulum-spesifik compiler flag'i içermez.
`language: cpp` ve `cpp_standard: c++20` taşınabilir runtime anahtarlarıdır.

```text
yerel kaynaklar
    ↓
Problem Factory ──→ doğrulanmış problem paketi
                         ↓
Platform problem bankası / test orchestration / output checker
                         ↓
                execution adapter (cpp+c++20 mapping)
                         ↓
                       Judge0
```

Problem Factory yalnızca paket üretimi, local oracle ve deterministik testlerden sorumludur.
Platform ürün ve değerlendirme davranışını sahiplenir. Judge0 yalnızca izole derleme/çalıştırma
motorudur. Bu ayrım sayesinde başka bir execution engine'e geçiş problem paketlerini veya problem
bankasını yeniden üretmeyi gerektirmez.

Opsiyonel `judge0-smoke`, bu sınırın entegrasyon kontrolüdür; paket veya pipeline state'i üzerinde
yazma yapmaz ve LLM çağrısı başlatmaz.
