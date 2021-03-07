FROM ubuntu:xenial

ENV BLENDER_VERSION 2.81

# Add Python 3.6 package repo
RUN apt-get update
RUN apt-get install -y software-properties-common
RUN add-apt-repository ppa:deadsnakes/ppa

# Update/upgrade and install system dependencies
RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install --no-install-recommends -y \
    libsdl1.2debian \
    libglu1 \
    python3.6 \
    python3.6-dev \
    python3.6-venv \
    bash \
    wget \
    bzip2 \
    make \
    libxi6 \
    libxrender1

# Retrieve and install pip for version 3.6 (not in above PPA)
RUN wget https://bootstrap.pypa.io/get-pip.py
RUN python3.6 get-pip.py

RUN pip3 install --upgrade pip
RUN pip3 install --upgrade setuptools

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY tests/install_blender.sh .

RUN bash install_blender.sh ${BLENDER_VERSION}

VOLUME /workdir
WORKDIR /workdir

ENTRYPOINT ["tests/entrypoint.sh"]
