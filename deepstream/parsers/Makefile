# Build inside the DeepStream 6.3 image:  make -C deepstream/parsers
DS_INC ?= /opt/nvidia/deepstream/deepstream/sources/includes
CUDA_INC ?= /usr/local/cuda/include
CXXFLAGS = -O2 -Wall -Wextra -fPIC -std=c++14 -I$(DS_INC) -I$(CUDA_INC)
TARGET = libnvdsparse_yolo12_lpr.so

$(TARGET): nvdsparse_yolo12_lpr.cpp
	$(CXX) $(CXXFLAGS) -shared -o $@ $<

clean:
	rm -f $(TARGET)
