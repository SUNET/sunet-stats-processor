DOCKER_STATS_PROCESSOR ?= /var/lib/stats_processor
DOCKER_STATS_PROCESSOR_CONFIG ?= /etc/stats_processor/config.yaml
DOCKER_STATS_PROCESSOR_PORT ?= 127.0.0.1:8000

docker_build:
	docker build . -t 'stats_processor:latest'

docker_run:
	docker run --rm -it --name stats_processor \
		-e STATS_PROCESSOR_CONFIG=/etc/stats_processor/config.yaml \
		-v $(DOCKER_STATS_PROCESSOR_CONFIG):/etc/stats_processor/config.yaml \
		-v $(DOCKER_STATS_PROCESSOR):/var/lib/stats_processor \
		-p $(DOCKER_STATS_PROCESSOR_PORT):8000 \
		'stats_processor:latest'

compose_up:
	./bin/docker-compose -p ici -f stats-processor-compose.yaml up -d

compose_down: compose_stop

compose_stop:
	./bin/docker-compose -p ici -f stats-processor-compose.yaml stop

compose_logs:
	./bin/docker-compose -p ici -f stats-processor-compose.yaml logs -f

test_telegraf:
	docker run --rm -it --net host --expose=8125/udp \
		-v $(PWD)/test_telegraf.conf:/etc/telegraf/telegraf.conf:ro \
	        docker.sunet.se/eduid/telegraf:staging

test_nc:
	bash -c 'i=100000; while [ 1 ]; do sleep 10; i=$$(($$i + ($${RANDOM} % 100))); echo "test.counter:$$i|c" | nc -w 1 -u 127.0.0.1 8125; done'

test_influxdb:
	docker run --rm -it --net host --expose=8086/tcp \
	        docker.sunet.se/eduid/influxdb:staging


.PHONY: docker_build docker_run compose_up compose_down compose_stop compose_logs
