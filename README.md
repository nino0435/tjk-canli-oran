# tjk-canli-oran

TJK günlük yarış programı sayfalarından koşu öncesi **canlı ganyan oranı** ve **AGF yüzdesi/sırası** anlık görüntülerini (snapshot) toplayan bağımsız araç. Yalnızca Python standart kütüphanesini kullanır; harici paket gerektirmez.

## Veri Düzeni (`veri` dalı)

GitHub Actions üzerinde çalışan toplayıcı, yakalanan satırları `veri` dalına İstanbul takvim gününe göre gruplanmış UTF-8 gzip CSV dosyaları olarak yazar:

```text
<YYYY-MM-DD>/<HHMMSS>.csv.gz
```

Her `.csv.gz` dosyası başlık satırı içerir ve şu sütunlardan oluşur:

| Sütun | Açıklama |
| --- | --- |
| `captured_at` | Yakalama zamanı (ISO 8601, `Europe/Istanbul`) |
| `race_id` | Koşu kimliği (`YYYY-MM-DD_Şehir_KoşuNo`) |
| `prog_no` | Program / forma sırası numarası |
| `ganyan_live` | Canlı ganyan oranı (henüz açılmamışsa boş) |
| `agf_pct` | AGF oynanma yüzdesi |
| `agf_rank` | AGF sırası |
| `race_time` | Planlanan koşu saati (`SS:DD`, İstanbul) |
| `minutes_to_post` | Koşu başlangıcına kalan dakika |

## Çalıştırma

Tek seferlik anlık görüntü toplamak için:

```bash
python collect.py --db live.db --once
```

Belirli bir süre boyunca (ör. 60 dakika) aralıklarla toplamak ve ardından CSV dışa aktarmak için:

```bash
python collect.py --db live.db --max-runtime-min 60
python export.py --db live.db --out-dir veri --state /tmp/export_state.json
```

## Not

Bu araç yalnızca halka açık TJK günlük yarış programı sayfalarını makul aralıklarla (normalde 180 saniye, koşuya yakın en sık 60 saniye) okur.
