#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_STUDENTS 16
#define NAME_LENGTH 50

// Enum for student grades
typedef enum {
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_D,
    GRADE_F
} Grade;

// Structure to represent a student
typedef struct {
    int id;
    char name[NAME_LENGTH];
    Grade grade;
} Student;

// Database structure
typedef struct {
    Student students[MAX_STUDENTS];
    int student_count;
} Database;

// Function prototypes
void addStudent(Database *db, int id, const char *name, Grade grade);
Student *searchStudent(Database *db, int id);
void displayStudent(const Student *student);
void displayAllStudents(Database *db);

// some global variable.
Database db = { .student_count = 0 };

// Main function
int main() {
    // Add 10 students
    addStudent(&db, 1, "Allison", GRADE_A);
    addStudent(&db, 2, "Bob", GRADE_B);
    addStudent(&db, 3, "Charlie", GRADE_C);
    addStudent(&db, 4, "Diana", GRADE_A);
    addStudent(&db, 5, "Eve", GRADE_B);
    addStudent(&db, 6, "Frank", GRADE_F);
    addStudent(&db, 7, "Grace", GRADE_D);
    addStudent(&db, 8, "Hannah", GRADE_C);
    addStudent(&db, 9, "Ian", GRADE_A);
    addStudent(&db, 10, "Jack", GRADE_B);

    printf("All students:\n");
    displayAllStudents(&db);

    return 0;
}

// Function to add a student to the database
void addStudent(Database *db, int id, const char *name, Grade grade) {
    if (db->student_count < MAX_STUDENTS) {
        Student *new_student = &db->students[db->student_count++];
        new_student->id = id;
        strncpy(new_student->name, name, NAME_LENGTH - 1);
        new_student->name[NAME_LENGTH - 1] = '\0';
        new_student->grade = grade;
    } else {
        printf("Database is full. Cannot add more students.\n");
    }
}

// Function to search for a student by ID
Student *searchStudent(Database *db, int id) {
    for (int i = 0; i < db->student_count; i++) {
        if (db->students[i].id == id) {
            return &db->students[i];
        }
    }
    return NULL;
}

// Function to display a single student's details
void displayStudent(const Student *student) {
    const char *grade_strings[] = {"A", "B", "C", "D", "F"};
    printf("ID: %d\n", student->id);
    printf("Name: %s\n", student->name);
    printf("Grade: %s\n", grade_strings[student->grade]);
}

// Function to display all students
void displayAllStudents(Database *db) {
    for (int i = 0; i < db->student_count; i++) {
        displayStudent(&db->students[i]);
        printf("\n");
    }
}

