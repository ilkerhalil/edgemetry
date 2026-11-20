# Ölçümün kaybettiği yer: çağrının öteki ucu

Bir ödeme servisi yavaşladığında ilk sorulan soru bellidir: hangi çağrı yavaş?

Elimizdeki panolarda genelde şu vardır: `outbound.duration` metriği, `service` ve `status`
boyutlarıyla. Servisin dışarıya çıkan çağrılarının ortalamasını gösterir. Ama "dışarısı" tek bir yer
değil. Aynı servis ödeme API'sine de, kuyruğa da, kimlik doğrulama sunucusuna da gidiyor. Metrik
bunları tek kovaya atıyor.

Sebep kardinalite. Hedef adresi bir metrik boyutu yaparsan, her yeni endpoint yeni bir zaman serisi
açar: `payments.internal:8443`, `payments.internal:8444`, `auth.internal:443`, müşteriye özel onlarca
adres. Metrik depolarının çoğu bunu kabul etmez, kabul edenlerin faturası da kabul edilmez.

## Span'da cevap var, toplama yok

Span bu bilgiyi taşır. Bir giden çağrı span'inde hedef adres, port, işlem adı ve süre birlikte
durur. Eksik olan bilgi değil, o bilgiyi gruplayan sorgu.

İzleme ürünlerinin bir kısmı izleri yalnızca kimlikle açar: `trace_id` verirsin, şelaleyi görürsün.
"Bu servisin şu adrese giden çağrılarının son bir saatteki p95'i kaç" sorusu ise span'lar üzerinde
gruplama ister. Bazı kurumsal sürümlerde bu sorgu yok; span arama yok, sorgu dili yok, metrik
boyutlarında da hedef adresi taşıyamıyorsun. Ortada kalıyorsun: elinde milyonlarca span var, tek tek
okumaktan başka yol yok.

Bu yazı, o boşluğu kapatan küçük bir araçtan çıkıyor: **Edgemetry**. İddiası dar — "şu servisin şu
adrese giden çağrısı kaç milisaniye sürüyor" sorusuna span düzeyinde cevap vermek.

## Birim: kenar

Depolamanın temel birimi span değil, kenar: `(servis, hedef, işlem)` üçlüsü. Her kenar için sayı,
p50, p95, p99 ve hata oranı tutuluyor.

```
service     peer                      span     n     p50     p95     p99   err%
checkout    payments.internal:8443    POST   400  202.06  902.22  902.42    6.5
```

Bu satır, ürünün tamamını anlatıyor. "Ödeme API'sine giden POST çağrıları 400 kez yapıldı, medyanı
202 ms, p95'i 902 ms, çağrıların %6,5'i hata döndü."

Hedef adres nereden geliyor? Span özniteliklerinde tek bir standart yok; farklı SDK'lar farklı
anahtarlar yazıyor: `server.address`, `peer.service`, `net.peer.name`, `rpc.service`. Araç bunları
sırayla deniyor, port varsa ekliyor, hiçbiri yoksa veritabanı sistemine düşüyor. Sıra önemli, çünkü
yanlış anahtar seçimi sessizce yanlış cevap üretir.

## Kurulumu, istek yolunun dışında

Edgemetry bir OpenTelemetry Collector'ın yanına oturuyor. Collector span'ları hem mevcut APM'e hem
buraya gönderiyor:

```yaml
exporters:
  otlphttp/dynatrace:
    endpoint: ${env:DT_ENDPOINT}
  otlphttp/edgemetry:
    traces_endpoint: ${env:EDGEMETRY_ENDPOINT}
    headers:
      Authorization: "Bearer ${env:EDGEMETRY_TOKEN}"
```

Bu bir mimari tercih, tesadüf değil. Edgemetry çökerse uygulamanın çalışması etkilenmiyor, mevcut
APM'in verisi de kesilmiyor. Collector kendi kuyruğunda tutuyor, geri deniyor. Yani araç, izleme
sisteminin içine değil yanına giriyor.

## Kurulumun sessiz hatası: hedefsiz span

Bu tür bir aracın en tehlikeli hali, çalışıyor görünen halidir. Collector span gönderir, kayıt
sayısı artar, pano dolar; ama client span'larında hedef adres yoksa bütün sorgular boş döner.
Kullanıcı "araç bozuk" der, oysa sorun toplama katmanındaki bir dönüşüm kuralındadır.

Bunun için ayrı bir komut var:

```
$ edgemetry verify
service                    client spans   missing peer   coverage
---------------------------------------------------------------
gateway                             400              0     100.0%
legacy-api                           60             60       0.0%

1 service(s) below 95% coverage: no callee on the span,
so per-endpoint latency cannot be computed
```

Çıkış kodu 2. Yani bu kontrol bir CI adımına ya da kurulum betiğine takılabilir: kapsam eşiğin
altındaysa kurulum "tamam" sayılmaz.

## Ölçümler

Araç, gecikmesi bilinen sahte bir ödeme API'sine 400 istek attı: normalde 200 ms, her dört çağrıdan
biri 900 ms, her yirmide bir hata.

| | gerçek | ölçülen |
|---|---|---|
| p50 | 200 ms | 202,06 ms |
| p95 | 900 ms | 902,22 ms |
| hata | %5 | %6,5 |

400 örnekte beklenen sapma. Pipeline uydurmuyor, ölçüyor.

Şelale tarafı da aynı şeyi söylüyor: sunucu span'i 206,66 ms, altındaki giden çağrı 201,66 ms, kalan
5 ms kendi işi. "Zamanın %97'si dış çağrıda" cevabı buradan çıkıyor — ve bu cevap, servis
metriklerinden çıkarılamaz.

100.000 span ile iki depo arka ucunu karşılaştırdım:

| | yazma | sorgu |
|---|---|---|
| SQLite | 1,76 s | 628,1 ms |
| PostgreSQL | 1,98 s | 191,7 ms |

Sorguda 3,3 kat fark var. Yazma tarafında PostgreSQL'in toplu yükleme yolu (`COPY`) ilk denemede
9,11 saniyeydi; satır satır `INSERT` yerine `COPY` kullanınca 1,98 saniyeye indi. Aynı iş, farklı yol.

## Neden ClickHouse değil

İlk tercih ClickHouse'du; span deposu için doğru araç olduğu açık. Ama bu makinede çalışmadı:
`Illegal instruction`. Sebep işlemcide AVX2 olmaması — eski bir Xeon. DuckDB de aynı sebeple düştü.

Bu bir ürün kararı değil, ölçüm kısıtı. Yazıyorum çünkü alternatifini ölçmeden "PostgreSQL yeterli"
demek istemiyorum. Elimdeki tek veri noktası şu: 100.000 span'da PostgreSQL, SQLite'tan 3,3 kat hızlı
sorguluyor. Müşteri donanımında ClickHouse ile kıyaslama henüz yapılmadı.

## Dürüst sınırlar

- **Tek düğüm, tek süreç.** Yatay ölçekleme yok.
- **Trend yok.** Her sorgu kendi penceresini tarıyor; "geçen haftaya göre p95 arttı mı" sorusu için
  özet tablo (rollup) gerekiyor, henüz yok.
- **Kimlik doğrulama paylaşılan bir token.** Kiracı bazlı yetkilendirme değil.
- **TLS yok.** Ters vekil ya da collector tarafında sonlandırılmalı.
- **Gerçek bir APM ortamında denenmedi.** Collector yapılandırması yazıldı, araç tarafı test edildi;
  ama canlı bir kurumsal izleme ortamına bağlanmadı.
- **Alım hızı ölçülmedi.** 100.000 span'ı toplu yazdım; saniyede kaç span aldığını ölçmedim.

Bu liste kısa değil ve kısalması için ölçüm gerekiyor, cümle değil.

## Durum

```
pip install "edgemetry[otlp,postgres]"
```

- 73 test, %90 kapsam, CI üç Python sürümünde yeşil
- Çekirdek sıfır bağımlılık: stdlib + SQLite; protobuf ve PostgreSQL opsiyonel
- OTLP/JSON ve OTLP/protobuf alımı
- `serve`, `query`, `trace`, `verify`, `prune`

Kod: https://github.com/ilkerhalil/edgemetry

## Kapanış

İzleme ürünlerinin çoğu "servis yavaş" der. Operasyonun ihtiyacı olan cümle daha dar: "şu adrese
giden çağrı yavaş, ve dün de yavaştı." Bu cümleyi kurmak için span'ı saklamak yetmiyor; span'ı
hedefe göre gruplayabilmek gerekiyor.

Ölçüm, iddiadan önce gelir. Bu yazıdaki her sayı, bu makinede çalıştırılmış bir komutun çıktısı.
