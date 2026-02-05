package com.example;

public class Sample {
    public String format(String name) {
        return  Hello  + name +  !;
    }

    private int multiply(int a, int b) {
        return a * b;
    }

    public static void main(String[] args) {
        Sample sample = new Sample();
        System.out.println(sample.format(Java) +  ->  + sample.multiply(3, 5));
    }
}
