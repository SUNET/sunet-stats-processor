FROM debian:testing

MAINTAINER eduid-dev <eduid-dev@SEGATE.SUNET.SE>

ENV DEBIAN_FRONTEND noninteractive
RUN apt-get -y update && apt-get -y install \
    git \
    python3-pip \
    python3.7-venv

COPY . /stats_processor/src
RUN (cd /stats_processor/src; git describe; git log -n 1) > /revision.txt
RUN rm -rf /src/.git
RUN python3.7 -m venv /stats_processor/env
RUN /stats_processor/env/bin/pip install -U pip wheel
RUN /stats_processor/env/bin/pip install -r /stats_processor/src/requirements.txt

EXPOSE "8000"

WORKDIR "/stats_processor/src"
ENV GUNICORN_CMD_ARGS="--bind=0.0.0.0:8000"
CMD [ "/stats_processor/env/bin/gunicorn", "stats_processor.app:api" ]
