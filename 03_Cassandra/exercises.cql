CREATE TABLE IF NOT EXISTS iot.latest_orders_by_customer (
  customer_id text, ts timestamp, order_id text, total double,
  PRIMARY KEY ((customer_id), ts, order_id)
) WITH CLUSTERING ORDER BY (ts DESC, order_id ASC);
CREATE TABLE IF NOT EXISTS iot.orders_by_day (
  day date, ts timestamp, order_id text, customer_id text, total double,
  PRIMARY KEY ((day), ts, order_id)
);
INSERT INTO iot.latest_orders_by_customer(customer_id,ts,order_id,total)
VALUES('C01','2026-11-17 09:00:00','O01',100);
INSERT INTO iot.orders_by_day(day,ts,order_id,customer_id,total)
VALUES('2026-11-17','2026-11-17 09:00:00','O01','C01',100);
CREATE TABLE IF NOT EXISTS iot.readings_by_sensor_month (
  sensor_id text, month text, ts timestamp, temperature double,
  PRIMARY KEY ((sensor_id, month), ts)
) WITH CLUSTERING ORDER BY (ts DESC);
INSERT INTO iot.readings_by_sensor_month(sensor_id,month,ts,temperature)
VALUES('hn-01','2026-10','2026-10-22 08:00:00',27.5);
INSERT INTO iot.readings_by_sensor_month(sensor_id,month,ts,temperature)
VALUES('hn-02','2026-10','2026-10-22 08:00:00',25.1);
INSERT INTO iot.readings_by_sensor_month(sensor_id,month,ts,temperature)
VALUES('hn-03','2026-10','2026-10-22 08:00:00',26.0);
