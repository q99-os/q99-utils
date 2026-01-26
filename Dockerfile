# 
FROM python:3.11

# 
WORKDIR /code

#
RUN pwd

# 
COPY ./requirements.txt /code/requirements.txt

# 
RUN pip install --upgrade -r /code/requirements.txt

COPY ./ /code/
