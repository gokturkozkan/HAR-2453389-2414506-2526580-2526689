# TDMA Evolution Notes

Bu dokuman, projedeki iletisim yapisinin eski TDMA mantigindan BLE soft-TDMA'ya ve oradan Wi-Fi soft-TDMA'ya nasil evrildigini net sekilde anlatmak icin hazirlandi.

## Kisa Ozet

Projede 3 farkli asama vardir:

1. Eski TDMA
2. BLE soft-TDMA
3. Wi-Fi soft-TDMA

Ucunde de ana hedef aynidir:

- birden fazla node'un ayni anda rastgele veri gondermesini engellemek
- veri iletimini zaman olarak duzenlemek
- cakis­ma ve kaybi azaltmak

Ama bunu yapis sekli zamanla gelismistir.

## 1. Eski TDMA

### Temel mantik

Eski yapida Raspberry Pi tamamen merkezi bir round robin polling yapiyordu.

- Pi her node'a sirayla gidiyordu
- once node 1, sonra node 2, sonra node 3
- her node'dan veri istemek icin tek tek komut gonderiyordu

Bu nedenle eski sistemde round robin cok acik sekilde vardi.

### Round robin nerede?

Eski Pi tarafi:

- `Hardware/RaspberryPi/tdma_formatted.py`
- `Hardware/RaspberryPi/tdma_hub.py`

Ozellikle mantik su sekildeydi:

- `FRAME_PERIOD / num_nodes` ile slot suresi hesaplanir
- `for slot_index, node_id in enumerate(active_nodes)` ile node'lar sirayla gezilir
- her node icin `request_sample(node_id, ...)` cagrilir

Bu fonksiyon seri hat uzerinden node'a `R` karakteri yollar.

Eski ESP32 tarafi:

- `Hardware/ESP32/NodeInit.ino`

Node burada su mantikla calisir:

- Bluetooth'tan gelen veri dinlenir
- eger gelen komut `R` ise `sendSensorFrame()` cagrilir
- yani node kendi kendine veri yollamaz
- Pi istemeden node konusmaz

### Eski TDMA'nin karakteri

Bu yapi tam anlamiyla:

- merkezi
- polling tabanli
- round robin kontrollu

Yani:

`Pi soruyor, node cevap veriyor.`

### Eski TDMA'nin eksikleri

- surekli sampling yoktu, istek geldikce veri gidiyordu
- veri ASCII/CSV formatinda gidiyordu
- sequence number yoktu
- packet loss ve duplicate takibi zayifti
- `/dev/rfcommX` yapisi kirilgandi
- bir node gecikirse tum dongu etkilenebiliyordu

## 2. BLE Soft-TDMA

### Temel mantik

Bu asamada klasik polling round robin terk edildi.

Pi artik:

- her node ile ayri BLE baglantisi kuruyor
- node'a tek tek "R" gondermiyor
- onun yerine `SYNC` paketi yolluyor
- node kendi slotunu hesaplayip o slotta veri gonderiyor

### Kullanilan dosyalar

- `Hardware/ESP32/NodeBleSoftTDMA.ino`
- `Hardware/RaspberryPi/tdma_ble_transport.py`
- `Hardware/RaspberryPi/tdma_ble_hub.py`

### BLE'de round robin nerede?

Burada round robin eski sistemdeki gibi "tek tek sample iste" seklinde degil.

Round robin mantigi artik:

- `slot index`
- `superframe`
- `next_seq_expected`

bilgileri uzerinden kuruluyor.

Pi tarafinda:

- `tdma_ble_hub.py` icindeki `ble_node_worker(...)`
- her node icin ayri async worker vardir
- worker periyodik olarak node'a `build_sync_packet(node_id)` ile `SYNC` yollar

Transport tarafinda:

- `tdma_ble_transport.py`
- `slot_index_for_node(...)`
- `build_sync_packet(...)`

Node tarafinda:

- `NodeBleSoftTDMA.ino`
- `handleSyncPacket(...)`
- `flushPendingDataIfDue()`

### BLE akisi nasil?

1. Node surekli sensor verisi toplar
2. Veri ring buffer'a yazilir
3. Pi node'a `SYNC` paketi yollar
4. Bu pakette node'un `slotIndex` bilgisi vardir
5. Node kendi iletim zamanini hesaplar
6. Slotu geldiginde buffered veriyi BLE notify ile toplu sekilde yollar
7. Pi sequence number ile kayip, tekrar, stale ve disconnect durumlarini takip eder

### BLE'nin eski TDMA'ya gore ilerlemeleri

- node surekli sample alir
- veri buffer'da tutulur
- tek sample yerine paketli veri gonderilir
- sequence number vardir
- `next_seq_expected` ile ack mantigi vardir
- `joining`, `synced`, `streaming`, `stale`, `disconnected` gibi durumlar izlenir
- prediction icin daha duzgun pencere uretilebilir

### BLE'nin siniri

- Pi her node ile ayri BLE connection tutmak zorundadir
- node sayisi artinca central tarafin yukü artar
- BLE connection/interference yonetimi daha hassastir

## 3. Wi-Fi Soft-TDMA

### Temel mantik

Wi-Fi asamasi BLE mantigini daha da ileri tasir.

Burada Pi:

- her node ile ayri baglanti kurmaz
- tum node'lara ayni anda ortak bir `SYNC` paketi broadcast eder

Node'lar:

- bu ortak zamani alir
- kendi slotunu `node_id` uzerinden hesaplar
- sadece kendi slotunda UDP ile veri yollar

### Kullanilan dosyalar

- `Hardware/ESP32/NodeInit.ino`
- `Hardware/ESP32/NodeConfig.h`
- `Hardware/RaspberryPi/tdma_wifi_transport.py`
- `Hardware/RaspberryPi/tdma_formatted.py`

### Wi-Fi'da round robin nerede?

Burada explicit polling round robin yoktur.

Onun yerine round robin mantigi zaman slotlarina donusmustur.

Slot atamasi su mantikla yapilir:

- `slot_start = sync_lead + (node_id - 1) * slot_length`

Bu mantik su dosyada bulunur:

- `Hardware/RaspberryPi/tdma_wifi_transport.py`
- `slot_start_us(...)`

Node tarafinda:

- `NodeInit.ino`
- `handleSyncPayload(...)`
- `maybeSendDataBatch()`

Pi tarafinda:

- `tdma_formatted.py`
- periyodik olarak `hub.build_sync_packet()` olusturulur
- UDP broadcast ile tum node'lara ayni anda yollanir

### Wi-Fi akisi nasil?

1. Tum node'lar ayni Wi-Fi agina baglanir
2. Node surekli sensor verisi toplar
3. Veri ring buffer'da tutulur
4. Pi ortak `SYNC` broadcast eder
5. Node bu paketten kendi slotunu hesaplar
6. Slotu geldiginde UDP `DATA` paketi yollar
7. Pi gelen `HELLO` ve `DATA` paketlerini toplar
8. Sequence takip edilir
9. Tum node verileri hizalanip backend `/predict`'e gonderilir

### Wi-Fi'nin BLE'ye gore ilerlemeleri

- Pi her node ile ayri connection yonetmez
- tek bir broadcast ile tum node'lari senkronize eder
- daha dagitilmis mimari elde edilir
- daha kolay olceklenir
- merkezi connection overhead azalir

## Round Robin Karsilastirmasi

### Eski TDMA

Round robin tipi:

- polling round robin

Kim kontrol ediyor?

- tamamen Raspberry Pi

Node davranisi:

- Pi isterse veri yollar

Ana cumle:

`Pi soruyor, node cevap veriyor.`

### BLE Soft-TDMA

Round robin tipi:

- slot atamali soft-TDMA

Kim kontrol ediyor?

- Pi slot bilgisini veriyor
- node kendi slotunda gonderiyor

Node davranisi:

- surekli topluyor
- slotu geldiginde notify ediyor

Ana cumle:

`Pi slot veriyor, node kendi sirasinda BLE ile gonderiyor.`

### Wi-Fi Soft-TDMA

Round robin tipi:

- broadcast senkronizasyonlu dagitilmis soft-TDMA

Kim kontrol ediyor?

- Pi ortak zamani dagitiyor
- node kendi slotunu kendisi uyguluyor

Node davranisi:

- surekli topluyor
- slotu geldiginde UDP ile yolluyor

Ana cumle:

`Pi ortak zaman dagitiyor, node kendi sirasini kendi uyguluyor.`

## Teknik Evrim Ozeti

Eski sistem -> BLE -> Wi-Fi cizgisi aslinda su gelismeyi gosterir:

### Eski sistem

- isteme temelli
- tek sample cevap modeli
- kirilgan baglanti yapisi

### BLE

- buffer tabanli
- packet tabanli
- sequence takipli
- state-aware
- ama hala per-node connection gerektiriyor

### Wi-Fi

- buffer tabanli
- packet tabanli
- sequence takipli
- broadcast sync ile daha dagitilmis
- daha olceklenebilir

## Hocaya Soylenebilecek Ozet

Sunumda veya sozlu anlatimda su paragraf kullanilabilir:

`Eski TDMA yapisinda Raspberry Pi, her sensor dugumunu sirayla poll eden merkezi bir round robin mantigiyla calisiyordu. Pi her node'a tek tek talep gonderiyor, node ise sadece o anda tek bir sensor cercevesi ile cevap veriyordu. BLE asamasinda bu yapi soft-TDMA'ya evrildi; Raspberry Pi her node ile ayri BLE baglantisi kurup senkronizasyon paketi gondermeye basladi, node ise surekli veri toplayip kendi slotunda toplu veri gonderdi. Wi-Fi asamasinda ise sistem daha da dagitildi; Raspberry Pi tum node'lara ortak bir SYNC paketi broadcast ediyor ve her node kendi slotunu node_id'sine gore hesaplayip UDP ile veri iletiyor. Boylece klasik polling round robin, zaman tabanli ve daha olceklenebilir bir soft-TDMA yapisina donusmus oldu.`

## Tek Cumlelik En Kisa Fark

- Eski TDMA: `Pi soruyor, node cevap veriyor`
- BLE soft-TDMA: `Pi slot veriyor, node kendi sirasinda BLE ile gonderiyor`
- Wi-Fi soft-TDMA: `Pi ortak zaman veriyor, node kendi sirasini kendi uyguluyor`
