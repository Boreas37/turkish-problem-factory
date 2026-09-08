# Tehdit modeli ve sınırlar

LLM'in ürettiği `reference.cpp` ve `generator.py` güvenilmez kabul edilir. Doğrulama bunları
ayrı bir geçici çalışma dizininde, kısıtlı ortam değişkenleriyle ve duvar saati, CPU, adres alanı,
çıktı dosyası, açık dosya ve süreç sınırlarıyla çalıştırır. Generator AST denetimi yalnızca
`json`, `random`, `math` ve `itertools` modüllerine izin verir; dosya, dinamik kod ve içe aktarma
kaçışlarını reddeder. C++ kaynak denetimi de ağ/dosya/süreç başlıklarını ve bilinen erişim,
shell, spawn, inline assembly ve mutlak host yolu kalıplarını reddeder. Secret ortam değişkenleri
alt sürece aktarılmaz. C++ ikilisi yalnızca paket dizininde çalıştırılır.

Bu korumalar bir üretim sandbox'ı değildir. Özellikle macOS/POSIX kaynak sınırları ağ ad alanı,
syscall filtresi, salt-okunur kök dosya sistemi veya güçlü süreç izolasyonu sağlamaz. macOS'ta
`RLIMIT_NPROC` kullanıcı geneline uygulandığı için süreç limiti atlanır; diğer limitler uygulanır.
Statik denetim kasıtlı obfuscation'a karşı güvenlik sınırı değildir. Kötü niyetli
derleyici girdisi teorik olarak derleyiciyi de hedefleyebilir. Pipeline'ı güvenilmeyen çok kiracılı
bir serviste çalıştırmayın. Üretim judge aşamasında Linux container/VM, kullanıcı ve ağ ad alanları,
seccomp, cgroup, salt-okunur imaj, ayrıcalıksız kullanıcı ve tek kullanımlık çalışma alanı gerekir.

Gelecekte öğrenci kaynak kodu FastAPI/backend sürecinde **asla doğrudan çalıştırılmamalıdır**.
Amaçlanan sınır `API → submission orchestration/queue → Judge0 → execution result` şeklindedir.
Judge0 ayrı ve izole execution altyapısı olarak konuşlandırılmalı; öğrenci süreçlerine uygulama
veritabanı, secret'lar veya iç servis ağı erişimi verilmemelidir. Bu repository production
submission servisini veya Judge0 deployment'ını kurmaz.

Zaman ölçümü yalnızca sonsuz döngü ve bariz taşmaları durdurur; Big-O sınıflandırması yapmaz.
Verimsiz çözümler, problem sınırlarından türetilmiş adversarial/stress girdileriyle elenir. İleride
yanlış çözümlerden oluşan bir mutant havuzu eklenerek test gücü ayrıca ölçülmelidir.
