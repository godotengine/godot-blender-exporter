FROM ubuntu:xenial

ENV BLENDER_VERSION 2.81

RUN apt-get update
RUN apt-get install --no-install-recommends -y \
    libsdl1.2debian \
    libglu1 python3-pip \
    bash \
    wget \
    bzip2 \
    make \
    libxi6 \
    libxrender1
RUN pip3 install --upgrade pip
RUN pip3 install --upgrade setuptools

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY tests/install_blender.sh .

RUN bash install_blender.sh ${BLENDER_VERSION}

VOLUME /workdir
WORKDIR /workdir

ENTRYPOINT ["tests/entrypoint.sh"]
