#!cython --cplus
# coding: utf-8


from libc.stdio cimport FILE
from libc.stdlib cimport malloc
from libc.stdlib cimport free
from libc.string cimport memcpy
from libc.errno cimport errno, EAGAIN

cdef extern from "stdio.h" nogil:
    ssize_t write(int fd, const void *buf, size_t count)
    ssize_t getline(char **lineptr, size_t *n, FILE *stream)

cdef extern from "Python.h":
    FILE* PyFile_AsFile(object p)


cdef inline ssize_t safe_write(int fd, const void* buf, size_t count) nogil:
    cdef ssize_t written = write(fd, buf, count)
    if written == -1:
        if errno == EAGAIN:
            written = 0
    return written

cdef class NonBlockingFeeder(object):
    cdef char*  in_rb # in_read_buffer
    cdef size_t in_rb_size
    cdef size_t in_rb_beg # index of begin data
    cdef size_t in_rb_end # index of end data

    cdef size_t max_lines_per_call
    cdef int fd

    def __cinit__(self):
        self.in_rb = NULL

    def __dealloc__(self):
        if self.in_rb:
            free(self.in_rb)

    def __init__(self, int fd, bytes header, size_t max_lines_per_call=0):
        self.fd = fd
        self.max_lines_per_call = max_lines_per_call

        self.in_rb_beg = 0
        self.in_rb_end = 0
        if header:
            self.in_rb_end = len(header)
            self.in_rb_size = self.in_rb_end
            self.in_rb = <char*>malloc(self.in_rb_size)
            if not self.in_rb:
                raise MemoryError('bad alloc')
            memcpy(self.in_rb, <void*><char*>header, self.in_rb_end - self.in_rb_beg)

    def is_empty(self):
        return not self.in_rb or self.in_rb_beg == self.in_rb_end

    def __call__(self, inf):

        cdef ssize_t written = 0

        cdef ssize_t lines_left = self.max_lines_per_call or -1
        cdef FILE* inf_stream = PyFile_AsFile(inf)

        # если self.line, то пишем её на fd
        if not self.is_empty():
            written = safe_write(self.fd, self.in_rb+self.in_rb_beg, self.in_rb_end - self.in_rb_beg)

        while <size_t>written == (self.in_rb_end-self.in_rb_beg) and lines_left != 0:
            self.in_rb_beg = self.in_rb_end = 0 # условине входа в цикл - всё записано до конца

            self.in_rb_end = getline(&self.in_rb, &self.in_rb_size, inf_stream) # читаем входной поток

            if not self.in_rb_end or not (self.in_rb_end+1):
                self.in_rb_end = 0 # обеспечит is_empty()
                return False # кончились данные, возвращаем False

            written = safe_write(self.fd, self.in_rb+self.in_rb_beg, self.in_rb_end - self.in_rb_beg)

            lines_left -= 1


        if written < 0 :
                raise Exception('write error %d' % errno)
        self.in_rb_beg += written

        return True
