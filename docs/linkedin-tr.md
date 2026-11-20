Metrikler "dışarıya giden çağrı yavaşladı" der. Hangisi olduğunu söylemez.

Sebep kardinalite: hedef adresi metrik boyutu yaparsan her endpoint yeni bir zaman serisi açar. Depolar bunu kabul etmez.

Span hedefi taşır. Ama izleri yalnız kimlikle açan ürünlerde "şu servisin şu adrese giden çağrısı kaç ms" sorusu cevapsız kalır.

Edgemetry bu boşluğu kapatıyor: span'ları saklıyor, çağıran ile çağrılan arasındaki her kenar için p50, p95, p99 ve hata oranı hesaplıyor.

Ölçüm — bilinen gecikmeli sahte ödeme API'si, 400 istek:

Gerçek: p50 200 ms, p95 900 ms, hata %5
Ölçülen: p50 202,06, p95 902,22, hata %6,5

100 bin span, iki arka uç:

SQLite yazma 1,76 s, sorgu 628 ms
PostgreSQL yazma 1,98 s, sorgu 192 ms

Sorguda 3,3 kat fark. ClickHouse bu makinede çalışmadı, işlemcide AVX2 yok. Ölçemediğim şeyi önermiyorum.

Kurulumun sessiz hatası için ayrı komut var: hedefsiz span varsa sorgular boş döner, satır sayısı ise sağlıklı görünür. verify kapsam %95 altındaysa çıkış kodu 2 veriyor.

Dürüst sınırlar: tek düğüm, trend yok, TLS yok, gerçek bir kurumsal APM ortamında denenmedi.

Kod: https://github.com/ilkerhalil/edgemetry

Sizin panonuz şu soruya cevap veriyor mu: ödeme API'sine giden çağrı dün kaç milisaniyeydi?

#OpenTelemetry #Observability #YazılımMimari #Performans
